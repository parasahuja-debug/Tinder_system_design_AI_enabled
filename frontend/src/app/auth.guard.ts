import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from './auth.service';

// Client-side gate on protected routes. This is a UX convenience only — the
// real security boundary is the gateway's auth_request (see CLAUDE.md's auth
// model): a stolen/expired token still gets a 401 from the API even if this
// guard is bypassed. Its job is just to avoid rendering a page that would
// immediately fail its API calls, and to bounce the user to /login instead.
export const authGuard: CanActivateFn = () => {
  if (inject(AuthService).getToken()) {
    return true;
  }
  return inject(Router).parseUrl('/login');
};
