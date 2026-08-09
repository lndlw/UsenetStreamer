# Stream release hard-kill fix

This version keeps the existing per-profile concurrent stream limit and active-stream admin UI, and adds true cancellation for the admin **Release** action.

When an admin releases a session:
- every HTTP connection belonging to that `(profile, type:id)` session gets an AbortController;
- the downstream client response is destroyed;
- the upstream Axios/WebDAV request receives the same abort signal;
- the session is removed from concurrency accounting immediately.

The admin JavaScript initialization call is also restored so the Active Streams UI and configuration controls initialize on page load.
