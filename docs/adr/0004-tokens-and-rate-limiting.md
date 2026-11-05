# ADR-0004: Short-lived access tokens, rotating refresh tokens in a cookie, and in-memory rate limiting

- **Status:** Accepted
- **Date:** 2026-11-02
- **Milestone:** 1.2 Identity and access (issues #15 and #16)

## Context

Hospital staff sign in to a system that holds medical and pharmacy data, so a stolen
session must be short-lived and must be possible to end. The web app (Phase 2) keeps the
access token in memory only, never in `localStorage`, and restores the session after a page
reload through a refresh cookie (plan §8.1).

The token pair this ADR builds on:

- **Access token:** an HS256 JWT, valid for 15 minutes, holding only the user's id, the
  issue time and the expiry. It is checked by its signature, so it can't be revoked; every
  request still loads the user from the database, so a deactivated account is refused at
  once.
- **Refresh token:** a random opaque value, valid for 7 days. The database stores only its
  SHA-256 hash. It travels only in a cookie that is `HttpOnly`, `SameSite=Strict`, limited
  to `Path=/api/v1/auth`, and `Secure` in production, so page scripts can never read it.

Four questions were left open by that design, and each is decided below.

## Decision

### 1. A fixed 7-day refresh window

- A refresh token lasts 7 days **from sign-in**.
- Each refresh swaps the token for a new one, and the new one **keeps the old expiry**.
  Refreshing never extends the session.
- After 7 days the user signs in again, however active they have been.
- **The one exception is a password change.** It starts a fresh 7-day session for the
  device that made the change, because it is a deliberate re-authentication with the
  current password.

**Why:** a stolen cookie has a hard limit. With a sliding window, where each refresh adds
another 7 days, a thief who keeps refreshing could stay signed in forever. Staff re-enter
their password at least once a week, which suits a system holding sensitive data.

### 2. Strict reuse detection, with a row lock

- Each refresh token works **once**. Using it revokes it and links it to its replacement
  through `replaced_by_id`.
- If a token that was already used comes back, the server assumes a copy exists. It revokes
  **every** refresh token of that user and logs a warning naming the user and the token's
  id, never the token itself.
- That revocation is **committed before the 401** is returned, so it isn't lost when the
  failed request is rolled back.
- The token's row is read with `SELECT ... FOR UPDATE`, which locks it until the request
  finishes.
- *Added 2026-11-05 (review run 1, R-022):* before the token's row, refresh locks the
  **user's** row (`SELECT ... FOR NO KEY UPDATE`), and a password change locks the user's
  row first too. Revoking every token is one `UPDATE`, which sees only the tokens committed
  when it starts, so without the user lock a refresh that was halfway through when the
  alarm or a password change ran kept the new token it issued. The two locks are always
  taken in that order: the other order lets two requests wait for each other until
  PostgreSQL aborts one of them.
- *Added 2026-11-05 (review run 1, R-025):* a sign-in takes the same user lock once its
  password has passed, and is refused if the stored hash changed during the check, so a
  sign-in with the old password can't outlive a password change. It doesn't lock before
  the check: failed sign-ins of an existing account would then wait for each other, while
  those for an unknown email never wait, and the difference would reveal which accounts
  exist.
- *Added 2026-11-05 (review run 1, R-028):* a sign-out locks its token the same way, so a
  refresh of the same cookie can come first and rotate it. The sign-out then revokes the
  replacement, which that refresh sends to the same browser, possibly after the sign-out
  has deleted the cookie; left alone, it would restore the session that was just ended.

**Why:** when a used token comes back, the server can't tell the real user from a thief,
so ending every session is the only safe answer: the real user signs in again, and the
thief is locked out. The lock prevents a race. Without it, two requests sent at the same
moment with the same cookie could both see the token as unused and both rotate it, turning
one token into two valid sessions that slip past reuse detection. With the lock, the second
request waits, then sees that the token is already used.

### 3. Reuse means a *rotated* token presented again

- The alarm fires only for a revoked token that **has** a `replaced_by_id`, meaning it was
  swapped during a refresh.
- A token revoked any other way gets an ordinary 401, with no warning and no revoking of
  the other sessions. That covers sign-out, a password change, deactivation, and an earlier
  alarm: none of them leaves a replacement.

**Why:** this rule replaced a stricter one that treated every revoked token as reuse, after
testing the password change exposed a bug. A user changed their password on a laptop while
a phone still held its old cookie, which the change had revoked. The phone refreshed in the
background, the old rule took that for theft, and the laptop's brand-new session was
revoked too. Only a rotated token proves that a copy exists; a token the server ended on
purpose is already dead, so refusing it quietly loses nothing. As a bonus, after an alarm
revokes everything, a thief retrying the same token gets quiet 401s instead of an alarm on
every attempt.

### 4. In-memory rate limiting

*Planned in issue #16 (IAM-3); nothing of it is built yet.*

- Sign-in and portal activation are limited per IP address and per account.
- Over the limit, the API returns `429 RATE_LIMITED`.
- The counters live in the application's memory.

**Why:** the application runs as a single instance, so in-memory counters are correct, and
they need no extra service such as Redis: nothing more to run or to pay for.

## Alternatives considered

**A sliding refresh window,** where each refresh adds another 7 days. More convenient, but
a session has no upper limit, and neither does a stolen cookie. Rejected.

**A grace period after rotation,** where a just-used token keeps working for a few seconds
so that two browser tabs refreshing together don't sign the user out. Friendlier, but it
opens a window for a thief and makes the rule harder to reason about. Rejected.

**Treating every revoked token as reuse.** Built first and replaced by decision 3: it signs
out the device that has just changed its password whenever another device refreshes.

**A shared store such as Redis for the rate-limit counters.** Correct for several instances,
but an extra service this single-instance deployment doesn't need yet.

## Consequences

**Gained**

- A stolen refresh cookie works for at most 7 days, and as soon as both the real user and
  the thief have used it, the alarm ends every session.
- Two simultaneous refreshes with one cookie can never create two sessions.
- Changing a password ends the sessions on every other device without signing out the
  device that made the change, and without a false alarm in the security log.

**Given up**

- A user who is active every day still signs in again once a week.
- Two tabs refreshing at almost the same moment can trigger the alarm and sign the user
  out. **The web app must make sure only one refresh runs at a time.**
- A token revoked by a sign-out raises no alarm if it is presented again. It can't do
  anything, so this is accepted.
- An access token keeps working for up to 15 minutes after sign-out or a password change,
  since it can't be revoked; the web app drops it from memory.
- The rate-limit counters reset when the application restarts.

**Known and accepted**

- The refresh cookie's `Max-Age` is reset to 7 days on each refresh, even though the token
  inside it expires sooner. The server checks the real expiry, so this is harmless.
- The current-password check in `POST /auth/change-password` isn't rate limited yet, so
  someone holding a stolen access token could keep guessing the current password. Issue
  #16 should cover it alongside sign-in.

**When to revisit**

- Running more than one instance of the API: the rate-limit counters must move to a shared
  store such as Redis.
- Complaints from users signed out by parallel tabs, if the web app can't keep refreshes to
  one at a time.

## References

- Plan §8.1 (authentication rules) and §11 (the auth endpoints).
- `backend/app/modules/auth/service.py`: `login`, `refresh`, `logout` and
  `change_password`.
- `backend/app/modules/auth/repository.py`: `get_refresh_token_by_hash` (the row lock),
  `get_refresh_token_by_id_for_update` (the replacement's lock at sign-out), and
  `revoke_all_refresh_tokens_for_user`.
- `backend/app/modules/users/service.py`: `get_user_by_id_for_update` (the user's row
  lock).
- `backend/app/core/security.py`: the access token and the refresh cookie.
- Tests in `backend/tests/test_auth_service.py` and `backend/tests/test_auth_api.py`,
  including `test_another_device_refreshing_after_a_change_keeps_this_session`, and the
  race tests in `backend/tests/test_auth_concurrency.py`.
