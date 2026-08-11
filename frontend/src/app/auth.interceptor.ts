import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';

import { AuthService } from './auth.service';

// Runs on every outgoing HttpClient request. Purpose: the gateway's
// auth_request gate expects an `Authorization: Bearer <token>` header on
// protected routes (see gateway/conf.d/default.conf) — this is the one place
// that header gets attached, so individual pages/services never repeat that
// logic or risk forgetting it on a new call.
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const token = inject(AuthService).getToken();

  // Requests before login (e.g. the login/register calls themselves) have no
  // token yet — send them through unmodified rather than attaching "Bearer null".
  if (!token) {
    return next(req);
  }

  return next(
    req.clone({
      setHeaders: { Authorization: `Bearer ${token}` }
    })
  );
};
