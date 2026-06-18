# OAuth setup

You register **your own** Google and Strava apps. This keeps you in full control
of your data and access, and means no shared backend ever sees your tokens. It
takes ~10 minutes once.

---

## 1. Google (Gmail) — Desktop OAuth client

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create
   (or pick) a project.
2. **APIs & Services → Library →** enable **Gmail API**.
3. **APIs & Services → OAuth consent screen:**
   - User type: **External** (or Internal if you use Google Workspace).
   - Fill in app name, your email, and a contact email.
   - **Scopes:** you do not have to add scopes here; the app requests
     `gmail.modify` at runtime.
   - **Test users:** add your own Gmail address. While the app is in "Testing"
     status, only listed test users can authorize it — which is exactly what you
     want for a personal tool. (No Google verification is needed for personal
     use with test users.)
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID:**
   - Application type: **Desktop app**.
   - Note the **Client ID** and **Client secret**.
5. Put them in your `.env`:
   ```
   GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=xxxx
   ```

> **Why `gmail.modify` and not `gmail.readonly`?** The tool reads receipts *and*
> adds a label to each email after uploading it, so the same ride is never
> uploaded twice. Labelling requires write access. The tool never deletes or
> sends mail. See [SECURITY.md](SECURITY.md).

---

## 2. Strava — API application

1. Go to [Strava API settings](https://www.strava.com/settings/api) and create an
   application.
2. Fields:
   - **Application Name:** anything, e.g. `citibike2strava`.
   - **Category:** Data Importer.
   - **Authorization Callback Domain:** `localhost`  ← important.
3. After creating, copy the **Client ID** and **Client Secret** into `.env`:
   ```
   STRAVA_CLIENT_ID=12345
   STRAVA_CLIENT_SECRET=xxxx
   ```

> The tool requests the `activity:write` and `read` scopes — enough to upload an
> activity and set its type. It cannot read your existing activities feed
> (that would need `activity:read_all`).

---

## 3. Authorize

```bash
citibike2strava login
```

This opens your browser twice (Google, then Strava). Each consent screen runs
against *your* app; the resulting refresh tokens are saved locally under
`~/.config/citibike2strava/tokens/` with `0600` permissions.

Verify:

```bash
citibike2strava status
```

To revoke later: `citibike2strava logout` (removes local tokens), and optionally
remove access at
[Google account permissions](https://myaccount.google.com/permissions) /
[Strava apps](https://www.strava.com/settings/apps).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Missing Google/Strava OAuth credentials` | `.env` not loaded or keys unset. Run from the repo dir or set env vars; check `citibike2strava status`. |
| Google `access_blocked` / app not verified | Add your address under **OAuth consent screen → Test users**. |
| Strava `redirect_uri` / `Bad Request` on login | Callback domain must be exactly `localhost`. Port `8721` is used locally; free it if in use. |
| Browser didn't open | Copy the printed URL manually. On headless boxes, run `login` where a browser is reachable, then copy `~/.config/citibike2strava/tokens/` over. |
