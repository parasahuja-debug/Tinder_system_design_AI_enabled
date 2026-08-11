import { Injectable, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, tap } from 'rxjs';

// Shape returned by both auth_service endpoints (see auth_service/main.py
// TokenResponse) — kept in sync manually since there's no shared schema yet.
export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface Credentials {
  email: string;
  password: string;
}

const TOKEN_KEY = 'tinder_access_token';

// Owns the JWT lifecycle in the browser: requesting it (register/login),
// storing it, and clearing it (logout). Every other part of the app (the
// route guard, the interceptor, pages) reads the token through this service
// instead of touching localStorage directly, so the storage key only lives
// in one place.
@Injectable({ providedIn: 'root' })
export class AuthService {
  // Signal so templates/guards can react to login state changing without
  // manually re-checking localStorage; seeded from any token already stored
  // (e.g. a page refresh) so a reload doesn't force a re-login.
  readonly isLoggedIn = signal<boolean>(!!localStorage.getItem(TOKEN_KEY));

  constructor(private http: HttpClient) {}

  // Paths are relative (/auth/register) — proxy.conf.json forwards them to
  // the gateway in dev; in a real deploy the app would be served behind the
  // same gateway origin, so no base URL is needed either way.
  register(creds: Credentials): Observable<TokenResponse> {
    return this.http
      .post<TokenResponse>('/auth/register', creds)
      .pipe(tap((res) => this.storeToken(res.access_token)));
  }

  login(creds: Credentials): Observable<TokenResponse> {
    return this.http
      .post<TokenResponse>('/auth/login', creds)
      .pipe(tap((res) => this.storeToken(res.access_token)));
  }

  logout(): void {
    localStorage.removeItem(TOKEN_KEY);
    this.isLoggedIn.set(false);
  }

  getToken(): string | null {
    return localStorage.getItem(TOKEN_KEY);
  }

  private storeToken(token: string): void {
    localStorage.setItem(TOKEN_KEY, token);
    this.isLoggedIn.set(true);
  }
}
