# Prompt Plan: Universal `net/http/pprof` Integration for Go Services

**Goal:** Given *any* Go service repo (net/http, gorilla/mux, chi, httprouter, echo, gin, fiber, httprequest, go-restful, etc.), detect the framework in use and wire up `net/http/pprof` on a **separate port**, preferring **9987**, without disrupting the existing app's routing, middleware, or main listener.

This doc is written so you can hand it directly to a coding agent (Claude Code, etc.) as a task spec, or run through it manually phase by phase.

---

## Phase 0 — Repo Reconnaissance

1. Run `find . -name "go.mod"` to locate module root(s) — monorepos may have several services.
2. Inspect `go.mod` `require` block for framework signatures:
   | Import path | Framework | Category |
   |---|---|---|
   | `github.com/gorilla/mux` | gorilla/mux | HTTP router |
   | `github.com/go-chi/chi` (v4/v5) | chi | HTTP router |
   | `github.com/julienschmidt/httprouter` | httprouter | HTTP router |
   | `github.com/labstack/echo` (v3/v4) | echo | HTTP router |
   | `github.com/gin-gonic/gin` | gin | HTTP router |
   | `github.com/gofiber/fiber` (v2/v3) | fiber | HTTP router |
   | `github.com/juju/httprequest` | httprequest | HTTP router (thin wrapper over net/http) |
   | `github.com/emicklei/go-restful` | go-restful | HTTP router |
   | `github.com/kataras/iris` | iris | HTTP router |
   | `github.com/gobuffalo/buffalo` | buffalo | HTTP router (wraps gorilla/mux internally) |
   | `github.com/go-kratos/kratos` | kratos | HTTP+gRPC framework — its HTTP transport wraps its own mux; treat like an HTTP router for pprof purposes |
   | `github.com/astaxie/beego` / `github.com/beego/beego` | beego | HTTP router **with caveat** — see 0.2 below |
   | `sigs.k8s.io/controller-runtime` | controller-runtime | **Manager-owned runtime**, no app-level HTTP router — see 0.2 below |
   | `github.com/zeromicro/go-zero` | go-zero | Framework with a **built-in DevServer** ops port — see 0.2 below |
   | `gofr.dev` | GoFr | Framework with **built-in pprof** on its metrics port — see 0.2 below |
   | `google.golang.org/grpc` (and no HTTP router import above) | plain gRPC service | **No HTTP router at all** — see 0.2 below |
   | *(none of the above)* | plain `net/http` | HTTP router |
3. Grep for the actual listener call to find the real entrypoint — don't just trust `main.go`:
   ```
   grep -rn "ListenAndServe\|\.Run(\|Serve(\|mgr.Start\|grpc.NewServer" --include="*.go" .
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

### 0.2 — Frameworks That Don't Fit the "Router + ListenAndServe" Model

A handful of frameworks either ship their own native pprof toggle, or have no HTTP router at all. Detecting these up front avoids bolting on a redundant/wrong-shaped fix. **When one of these is detected, prefer its native mechanism over the generic Phase 2 template** — it's more idiomatic and avoids fighting the framework's own lifecycle/shutdown handling.

- **controller-runtime (Kubernetes operators/controllers).** Since controller-runtime `v0.15.0`, the `Manager` has a built-in `Options.PprofBindAddress` field — no manual `net/http/pprof` import or custom server needed at all. Just set it in the existing `ctrl.Options{}` struct passed to `ctrl.NewManager(...)`:
  ```go
  mgr, err := ctrl.NewManager(ctrl.GetConfigOrDie(), ctrl.Options{
      Scheme:                 scheme,
      Metrics:                server.Options{BindAddress: ":8080"},
      HealthProbeBindAddress: ":8081",
      PprofBindAddress:       ":9987", // was likely unset, or on 6060/8082
      // ... rest of existing options unchanged
  })
  ```
  Check for port collisions against the manager's *other* internal servers too — metrics (commonly `:8080` or `:8443`), health probes (commonly `:8081`), and the webhook server (commonly `:9443`) — not just the app's main traffic port. If the repo is on a controller-runtime version older than v0.15.0, there's no built-in field; fall back to the generic Phase 2 pattern, added as a separate `Runnable` registered via `mgr.Add(...)` so it shares the manager's shutdown lifecycle instead of a bare goroutine.

- **go-zero.** Has a built-in `DevServer` ops block (`service.ServiceConf.DevServer` in `rest.RestConf`/`zrpc.RpcServerConf`) that already centralizes health and metrics on one dedicated port, separate from the main service port. Check the installed go-zero version's `devserver` package for whether pprof is bundled into that same block (this has evolved across versions) — if so, just point `DevServer.Port` at `9987` rather than hand-rolling a second server; if not, add the generic Phase 2 server alongside the existing `DevServer` port (pick a different port than DevServer to avoid a collision).

- **GoFr.** Ships pprof enabled by default, served on its `METRICS_PORT` config value (defaults to `2121`). Just set `METRICS_PORT=9987` in the app's config/env rather than adding any code — check for a collision with GoFr's own metrics usage of that same port first, since GoFr multiplexes pprof and metrics onto it together.

- **beego.** Beego re-implements its own `ServeHTTP`, so the plain blank-import trick (`_ "net/http/pprof"`) does not automatically attach to beego's router the way it does for plain `net/http`. Beego instead exposes profiling through its admin/toolbox module — check `web.conf`/`app.conf` for `EnableAdmin`, `AdminHttpAddr`, and `AdminHttpPort` (or the equivalent `web.BConfig.Listen` struct in code). Point `AdminHttpPort` at `9987` if enabling that module is acceptable; otherwise fall back to a fully standalone Phase 2 server (bound to its own port, with its own `http.ServeMux`) since beego's main router won't pick up `DefaultServeMux` registrations.

- **Plain gRPC services (grpc-go), with or without grpc-gateway.** gRPC servers don't run an HTTP router at all in the traditional sense — `grpc.NewServer()` + `lis.Accept()` speaks the gRPC wire protocol directly, so there's no `DefaultServeMux` collision risk to worry about. The generic Phase 2 template applies as-is: start the standalone pprof `http.Server` in a goroutine right next to wherever `grpcServer.Serve(lis)` is called in `main()`. If the repo also runs a grpc-gateway HTTP reverse proxy, treat *that* proxy's mux as the "main router" for collision-checking purposes (Phase 0.1 still applies to it).

- **Non-serving Go binaries (cron jobs, queue/Kafka consumers, CLI tools, one-shot batch jobs).** These have no long-running listener to hang pprof off in the traditional sense. If profiling is still wanted, the generic Phase 2 server can be started conditionally (e.g. behind `ENABLE_PPROF`) inside `main()` regardless of the absence of a router — it just runs alongside whatever the binary's actual work loop is, and should be gated so it doesn't linger after a short-lived job exits without the operator asking for it.

### 0.3 — Fallback When the Framework Can't Be Identified

This plan can't enumerate every framework that exists, and a repo might use something not in the table above (a newer or niche router, an in-house wrapper, a framework this plan hasn't caught up to yet). Don't stall or guess wildly — fall back to this safe default procedure instead of skipping the task:

1. **Confirm it's actually a long-running service first.** Re-run the Phase 0 grep for `ListenAndServe`/`.Run(`/`Serve(`/`mgr.Start`/`grpc.NewServer`. If nothing matches at all, treat it as a non-serving binary (last bullet in 0.2) rather than forcing an HTTP-shaped fix onto it.
2. **If a listener exists but the framework is unrecognized**, inspect what's actually passed as the `Handler` to that listener call (or the object `.Run()`/`.Serve()` is a method on). Whatever it is — a custom in-house router, an unfamiliar third-party package, a struct that merely implements `http.Handler` — **the generic Phase 2 standalone server is always safe to apply regardless of what that handler is**, because it never touches the app's own router at all. This is the reason the standalone-server pattern was chosen as the default template throughout this plan: it doesn't require understanding the app's routing internals to be correct.
3. **Apply the Phase 2 template as-is**, wire it into `main()` next to the unidentified framework's listener call (same placement rule as every other framework: right before the blocking `Serve`/`Run`/`ListenAndServe` call), and run the full Phase 5 validation checklist to confirm both that pprof works on the new port *and* that it did not attach to the main app's port (this second check matters even more here, precisely because the framework's own `DefaultServeMux` behavior is unknown).
4. **Report the fallback explicitly.** State plainly in your output that the framework could not be identified against the known table, that the generic isolated-server fallback was used instead of a framework-native integration, and name the specific import paths / listener call that didn't match anything recognized — so a human reviewer knows to double check for a native pprof option this plan doesn't yet know about, and so this plan can be extended later.
5. **Never silently do nothing.** An unidentified framework is a reason to fall back to the generic template with a flagged report, not a reason to skip the task or ask the person to identify it themselves first — proceed with the safe default and let them override if a better native option turns out to exist.

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

> **Note:** If Phase 0.2 flagged the repo as controller-runtime, go-zero, GoFr, beego, or a router-less gRPC/worker service, use the corresponding approach from 0.2 instead of the templates below — those either have a native pprof option or a genuinely different lifecycle shape. The templates below cover conventional HTTP-router frameworks. **If the framework doesn't match anything in the table at all, skip straight to the Phase 0.3 fallback** — don't force-fit one of the named templates onto an unrecognized router.

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

### iris
Same pattern as echo/gin — iris has its own optional pprof middleware that mounts on the same app/port; for a separate port, use the standalone server:
```go
func main() {
	app := iris.New()
	// ... existing routes ...

	pprofSrv := StartPprofServer()
	defer StopPprofServer(pprofSrv)

	app.Listen(":8080")
}
```

### buffalo
Buffalo wraps gorilla/mux internally and typically starts via `app.Serve()`. Add the pprof call right before it, same as the gorilla/mux case:
```go
func main() {
	app := app.App()
	// ... existing routes ...

	pprofSrv := StartPprofServer()
	defer StopPprofServer(pprofSrv)

	if err := app.Serve(); err != nil {
		log.Fatal(err)
	}
}
```

### kratos (go-kratos)
Kratos apps are usually built with `kratos.New(kratos.Server(httpSrv, grpcSrv), ...)` and started via `app.Run()`. Add the pprof call before `app.Run()`, alongside wherever `http.NewServer(...)`/`grpc.NewServer(...)` are constructed — it doesn't need to touch either transport, since it runs as its own isolated listener:
```go
func main() {
	httpSrv := http.NewServer(http.Address(":8080"))
	grpcSrv := grpc.NewServer(grpc.Address(":9000"))
	// ... existing registration ...

	pprofSrv := StartPprofServer()
	defer StopPprofServer(pprofSrv)

	app := kratos.New(kratos.Server(httpSrv, grpcSrv))
	if err := app.Run(); err != nil {
		log.Fatal(err)
	}
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

> Detect which Go framework this repository uses by inspecting `go.mod` and the entrypoint's setup — a conventional HTTP router (net/http, gorilla/mux, chi, httprouter, echo, gin, fiber, iris, buffalo, kratos, httprequest, go-restful), a framework with a native pprof mechanism (controller-runtime's `PprofBindAddress`, go-zero's `DevServer`, GoFr's `METRICS_PORT`, beego's admin/toolbox module), or a router-less service (plain gRPC, a cron/worker/batch binary). Prefer a framework's native pprof mechanism over hand-rolling a server when one exists. **If the framework doesn't match any of these, don't stop or guess wildly** — fall back to a standalone, isolated `net/http/pprof` server wired in next to whatever listener call you did find, since that pattern is safe regardless of what the app's own router is, and clearly flag in your report that this was a fallback due to an unrecognized framework (name the unmatched import paths/listener call so it can be reviewed later). Also check whether pprof is already integrated anywhere in the repo, and branch accordingly:
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
> Report back: which framework was detected (or that it was unidentified and the fallback was used), which scenario applied (fresh install / port relocation / security fix), what file(s) were changed/added, the final port/env vars, and the curl commands to verify `/debug/pprof/` is reachable on the new port but not on the main app port.