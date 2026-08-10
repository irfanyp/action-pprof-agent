# Prompt Plan: Universal `net/http/pprof` Integration for Go Services

**Goal:** Given *any* Go service repo (net/http, gorilla/mux, chi, httprouter, echo, gin, fiber, httprequest, go-restful, etc.), detect the framework in use and wire up `net/http/pprof` on a **separate port**, preferring **9987**, without disrupting the existing app's routing, middleware, or main listener.

This doc is written so you can hand it directly to a coding agent (Claude Code, etc.) as a task spec, or run through it manually phase by phase.

---

## Phase 0 — Repo Reconnaissance

1. Run `find . -name "go.mod"` to locate module root(s) — monorepos may have several services.
2. Inspect `go.mod` `require` block for framework signatures:
   | Import path | Framework |
   |---|---|
   | `github.com/gorilla/mux` | gorilla/mux |
   | `github.com/go-chi/chi` (v4/v5) | chi |
   | `github.com/julienschmidt/httprouter` | httprouter |
   | `github.com/labstack/echo` (v3/v4) | echo |
   | `github.com/gin-gonic/gin` | gin |
   | `github.com/gofiber/fiber` (v2/v3) | fiber |
   | `github.com/juju/httprequest` | httprequest |
   | `github.com/emicklei/go-restful` | go-restful |
   | *(none of the above)* | plain `net/http` |
3. Grep for the actual listener call to find the real entrypoint — don't just trust `main.go`:
   ```
   grep -rn "ListenAndServe\|\.Run(\|Serve(" --include="*.go" .
   ```
4. Note whether the app uses `http.DefaultServeMux` implicitly (calls `http.Handle`/`http.HandleFunc` directly) — this matters because `net/http/pprof`'s side-effecting import (`_ "net/http/pprof"`) **also registers itself on `http.DefaultServeMux`**, which can silently double-expose pprof on the app's main port if the app also serves off DefaultServeMux. Always give pprof its own `*http.ServeMux` and its own `*http.Server` to avoid this collision.

**Output of this phase:** framework identified, entrypoint file/line identified, DefaultServeMux usage flagged.

### 0.1 — Detect Whether pprof Is *Already* Integrated

Before assuming a fresh install, grep for any existing pprof footprint:
```
grep -rn "net/http/pprof\|debug/pprof\|gin-contrib/pprof\|echo-contrib.*pprof\|fiber.*middleware/pprof\|pprof\.Register\|pprof\.Index\|pprof\.Profile" --include="*.go" .
```
Classify what you find into one of three states, then jump to the matching scenario:

| State | Signal | Go to |
|---|---|---|
| **No pprof present** | grep above returns nothing | Phases 1–6 (fresh install, as written above) |
| **Already integrated, properly isolated** | pprof is registered on its *own* `http.ServeMux`/`http.Server` bound to a distinct port (any port), separate from the app's main router | **Scenario A** (below) — just relocate the port |
| **Already integrated, improperly exposed** | pprof handlers are registered directly on the app's main router/mux (e.g. `router.PathPrefix("/debug/pprof").Handler(...)`, `r.GET("/debug/pprof/*", ...)`, `app.Use(fiberpprof.New())` on the main `app`, or the blank import combined with the app itself serving off `http.DefaultServeMux`) — meaning pprof is reachable on the **same port** as production traffic | **Scenario B** (below) — fix the isolation *and* relocate the port |

---

## Phase 1 — Port Selection Logic

1. Default candidate: **9987**.
2. Grep the repo and any k8s manifests / Dockerfiles / docker-compose for `9987` to check for collisions:
   ```
   grep -rn "9987" --include="*.go" --include="*.yaml" --include="*.yml" --include="Dockerfile*" .
   ```
3. If taken, fall back in this order: `9987` → `6060` (Go's conventional pprof port) → `0` (OS-assigned, logged on start).
4. Make the port **configurable** via env var, e.g. `PPROF_PORT`, defaulting to `9987`, so ops can override without a redeploy.
5. Bind to `127.0.0.1` by default, not `0.0.0.0` — pprof exposes stack traces, heap contents, and can trigger CPU profiling; it should not be reachable from outside the pod/host unless the operator explicitly opts in (e.g. via a second env var `PPROF_BIND_ADDR`).

---

## Phase 2 — Core Implementation (framework-agnostic core)

Create a new file, `pprofserver.go` (or `internal/debug/pprof.go` if the repo uses an internal packages layout), containing a self-contained starter function. This is the same for every framework, because pprof always rides on its own plain `net/http` server:

```go
package main // or appropriate package per repo layout

import (
	"context"
	"log"
	"net/http"
	_ "net/http/pprof" // side-effect: registers handlers on http.DefaultServeMux
	"os"
	"time"
)

// StartPprofServer starts a dedicated debug/profiling HTTP server.
// It is isolated from the application's main router/mux.
func StartPprofServer() *http.Server {
	addr := os.Getenv("PPROF_BIND_ADDR")
	if addr == "" {
		addr = "127.0.0.1"
	}
	port := os.Getenv("PPROF_PORT")
	if port == "" {
		port = "9987"
	}

	srv := &http.Server{
		Addr:              addr + ":" + port,
		Handler:           http.DefaultServeMux, // pprof registered itself here via blank import
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		log.Printf("pprof debug server listening on %s (endpoints under /debug/pprof/)", srv.Addr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Printf("pprof server error: %v", err)
		}
	}()

	return srv
}

// StopPprofServer gracefully shuts down the pprof server. Call from main's shutdown path.
func StopPprofServer(srv *http.Server) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = srv.Shutdown(ctx)
}
```

Guard the whole thing behind an env flag if you want it opt-in in production:
```go
if os.Getenv("ENABLE_PPROF") == "true" {
    pprofSrv := StartPprofServer()
    defer StopPprofServer(pprofSrv)
}
```

This block **never changes** across frameworks — it's plain `net/http`, so it works identically whether the app itself is gin, echo, fiber, chi, or raw net/http.

---

## Phase 3 — Wiring Into Each Framework's `main()`

The only per-framework work is **where** you call `StartPprofServer()` — always in `main()` (or the bootstrap function), never inside a request handler. Below is what to look for and what to add, per framework.

### Plain `net/http` / gorilla/mux / chi / httprouter / go-restful
These all eventually call something like `http.ListenAndServe(addr, router)`. Add the pprof call just before that line:
```go
func main() {
	router := mux.NewRouter() // or chi.NewRouter(), httprouter.New(), etc.
	// ... existing route registration ...

	pprofSrv := StartPprofServer()
	defer StopPprofServer(pprofSrv)

	log.Fatal(http.ListenAndServe(":8080", router))
}
```
No conflict risk here since `router` is its own handler, separate from `http.DefaultServeMux`.

### httprequest (juju)
`httprequest` builds handlers that get mounted onto a standard `http.ServeMux` or `httprouter` anyway — same pattern as above; add `StartPprofServer()` next to wherever the app's own `http.Server`/`ListenAndServe` is constructed.

### echo (v3/v4)
```go
func main() {
	e := echo.New()
	// ... existing routes ...

	pprofSrv := StartPprofServer()
	defer StopPprofServer(pprofSrv)

	e.Logger.Fatal(e.Start(":8080"))
}
```
Do **not** use `echo`'s own pprof middleware (`github.com/labstack/echo-contrib/pprofwrapper` or similar) if the requirement is a *separate port* — that middleware mounts pprof onto the same echo instance/port. Prefer the standalone server above unless the task explicitly asks for same-port exposure.

### gin
Same reasoning as echo — `gin-contrib/pprof` mounts on the same router/port. For a separate port, use the standalone server:
```go
func main() {
	r := gin.Default()
	// ... existing routes ...

	pprofSrv := StartPprofServer()
	defer StopPprofServer(pprofSrv)

	r.Run(":8080")
}
```

### fiber (v2/v3)
Fiber's built-in `middleware/pprof` also mounts on the same app/port. For isolation, use the standalone `net/http`-based server (fiber apps run on fasthttp, but that doesn't matter — the pprof server is a completely separate process-level listener):
```go
func main() {
	app := fiber.New()
	// ... existing routes ...

	pprofSrv := StartPprofServer()
	defer StopPprofServer(pprofSrv)

	log.Fatal(app.Listen(":8080"))
}
```

---

## Scenario A — pprof Already Integrated Properly, Just on the Wrong Port

Use this path when Phase 0.1 found pprof already running on its own isolated `http.Server`/`http.ServeMux`, just not on port 9987.

1. **Locate the existing pprof server construction** — search for the `http.Server{}` / `ListenAndServe` call that's paired with the pprof registration (it will *not* be the same `Addr` as the main app server).
2. **Change only the port**, preferring the same pattern already used by the repo:
   - If the port is hardcoded (e.g. `":6060"`), replace with an env-configurable value defaulting to `9987`:
     ```go
     port := os.Getenv("PPROF_PORT")
     if port == "" {
         port = "9987"
     }
     srv := &http.Server{Addr: "127.0.0.1:" + port, Handler: pprofMux}
     ```
   - If it's already env-configurable but with a different default/var name, just change the *default value* to `9987` — don't rename the env var, to avoid breaking existing ops tooling/dashboards/alerts that may reference it. Mention the var name in your report so operators know it's now `9987` by default.
3. **Do not touch** the rest of the existing setup (bind address, TLS if present, shutdown wiring, gating flag) — this scenario is a pure port relocation, nothing else was broken.
4. **Check for collisions** exactly as in Phase 1 before committing to 9987 — if something else in the repo already claims 9987, fall back to 6060 (or whatever was already there) and say so explicitly in your report.
5. Re-run the Phase 5 validation checklist against the *new* port.

**Do not** rewrite a working isolated setup into the Phase 2 template — if it ain't broken (i.e., it's not exposed on the main router), minimal diff is the goal.

---

## Scenario B — pprof Integrated Improperly (Exposed on the Main App Router/Port)

Use this path when Phase 0.1 found pprof reachable on the same port as production traffic — e.g. mounted directly on the app's router, or relying on the app itself serving off `http.DefaultServeMux` alongside the blank pprof import.

This is a two-part fix: **(1) remove the main-router exposure**, **(2) stand up the isolated server on the priority port**.

1. **Find every place pprof is reachable from the main router** and remove those registrations. Common patterns to strip out:
   - A route/group explicitly mounted on the app router, e.g. `router.PathPrefix("/debug/pprof/").Handler(http.DefaultServeMux)`, `r.Any("/debug/pprof/*any", gin.WrapH(...))`, `e.Any("/debug/pprof/*", ...)`, `app.Use(fiberpprof.New())` attached to the main `app`/`router`/`e` instance, or a manual `mux.HandleFunc("/debug/pprof/...", pprof.Index)` sitting next to the app's own routes.
   - If the app itself calls `http.ListenAndServe(addr, nil)` (nil handler ⇒ `http.DefaultServeMux`) and *also* blank-imports `net/http/pprof`, that's the improper case even with zero explicit route registration — the fix is to stop the app from serving off `DefaultServeMux` (give it its own explicit `*http.ServeMux`/router) so pprof's self-registration there is no longer reachable on the main port.
   - Remove any pprof-specific import that only served the main-router mounting (e.g. `gin-contrib/pprof`, `echo-contrib`'s pprof wrapper, `fiber`'s pprof middleware) if it's not reused elsewhere.
2. **Add the isolated server from Phase 2** (`StartPprofServer`), listening on the priority port (9987, with the same collision-check/fallback logic from Phase 1).
3. **Wire it into `main()`** per the Phase 3 pattern for the detected framework, in place of the removed inline registration.
4. **Double-check no residual exposure**: after the fix, `curl` the main app port's `/debug/pprof/` path — it must 404 or hit the app's normal not-found handler, not pprof's index page.
5. Call out explicitly in your report that this was a **security-relevant fix**, not just a port move — profiling endpoints on a public/production-facing port can leak memory contents, goroutine stacks, and allow triggering CPU profiling that affects service latency; that was reachable before and now is not.

---

## Phase 4 — Graceful Shutdown Integration

If the repo already has a signal-handling shutdown block (common pattern with `signal.NotifyContext` or `os/signal`), hook `StopPprofServer` into it rather than a bare `defer`, so it shuts down in the same wave as the main server:
```go
<-ctx.Done()
StopPprofServer(pprofSrv)
_ = mainSrv.Shutdown(shutdownCtx)
```

---

## Phase 5 — Validation Checklist

After wiring, verify:
- [ ] `go build ./...` passes.
- [ ] App starts, main port still serves normal traffic unaffected.
- [ ] `curl http://127.0.0.1:9987/debug/pprof/` returns the pprof index page.
- [ ] `curl http://127.0.0.1:9987/debug/pprof/goroutine?debug=1` returns a goroutine dump.
- [ ] Main app port does **not** also expose `/debug/pprof/*` (confirms no `DefaultServeMux` collision) — `curl http://127.0.0.1:8080/debug/pprof/` should 404 or route to the app's own 404 handler.
- [ ] If `ENABLE_PPROF` gating was added, confirm pprof server does *not* start when the flag is unset/false.
- [ ] Confirm port 9987 (or fallback) doesn't collide with any existing container `EXPOSE`/k8s `containerPort` — add it to Dockerfile/manifests if the operator wants it reachable outside `127.0.0.1` (with a clear warning about exposing profiling data).
- [ ] **Scenario A only:** confirm the diff touched *only* the port/default-value, not the existing isolation structure, shutdown wiring, or gating flag.
- [ ] **Scenario B only:** confirm `/debug/pprof/*` is no longer reachable on the main app port under any path/prefix that was previously registered, and confirm the new isolated server on 9987 works — the fix isn't done until both are true.

---

## Phase 6 — Deliverable Summary (what the agent should report back)

1. Detected framework(s) and entrypoint file(s)/line(s) modified.
2. New file added (`pprofserver.go` or equivalent) with its full path.
3. Port chosen and why (9987 vs fallback), and the env vars introduced (`PPROF_PORT`, `PPROF_BIND_ADDR`, `ENABLE_PPROF`).
4. Confirmation that no `DefaultServeMux` collision exists with the main app port.
5. The exact `curl` commands to validate, copy-pasted into the PR description.

---

## Ready-to-Paste Agent Prompt

> Detect which Go HTTP framework this repository uses (net/http, gorilla/mux, chi, httprouter, echo, gin, fiber, httprequest, go-restful, or other) by inspecting `go.mod` and the entrypoint's router/listener setup. Also check whether pprof is already integrated anywhere in the repo, and branch accordingly:
> - **If no pprof integration exists:** add a new one from scratch, isolated on its own port.
> - **If pprof is already integrated on its own isolated server/port, just not the priority port:** make the minimal change needed to move it to the priority port (9987, falling back to 6060 on collision) — don't restructure anything else that's already working.
> - **If pprof is already integrated but reachable on the same port/router as production traffic** (mounted on the main router, or the app serving off `http.DefaultServeMux` alongside a blank pprof import): remove the main-router exposure first, then stand up an isolated server on the priority port. Explicitly flag this as a security fix in your report, since it was previously leaking profiling data on a production-facing port.
>
> For the fresh-install or fixed case, add a self-contained, isolated `net/http/pprof` debug server that:
> - Listens on its own port, defaulting to **9987**, configurable via `PPROF_PORT` env var, falling back to 6060 if 9987 is already used elsewhere in the repo/manifests.
> - Binds to `127.0.0.1` by default (configurable via `PPROF_BIND_ADDR`), never `0.0.0.0`, since pprof exposes sensitive runtime data.
> - Uses its own `*http.ServeMux`/`*http.Server` so it never collides with the app's existing router or `http.DefaultServeMux`.
> - Starts as a goroutine from `main()` right before the app's main listener starts, and shuts down gracefully alongside the app's existing shutdown path (or via `defer` if none exists).
> - Is optionally gated behind an `ENABLE_PPROF` env var if the app runs in production.
> Report back: which framework was detected, which scenario applied (fresh install / port relocation / security fix), what file(s) were changed/added, the final port/env vars, and the curl commands to verify `/debug/pprof/` is reachable on the new port but not on the main app port.