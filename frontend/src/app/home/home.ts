import { Component, OnInit, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';

import { AuthService } from '../auth.service';

// Response shape from profile_service's Day-1 verification endpoint
// (see profile_service/main.py GET /profile) — it just echoes X-User-Id.
interface ProfileResponse {
  user_id: string;
  message: string;
}

// The protected landing page (behind authGuard). Purpose: prove the whole
// auth chain works from the browser, not just curl — on load it calls
// GET /profile, the interceptor attaches the JWT, the gateway validates it
// and injects X-User-Id, and profile_service echoes that id back here.
@Component({
  selector: 'app-home',
  standalone: true,
  templateUrl: './home.html'
})
export class Home implements OnInit {
  readonly userId = signal<string | null>(null);
  readonly errorMessage = signal<string | null>(null);

  constructor(
    private http: HttpClient,
    private auth: AuthService,
    private router: Router
  ) {}

  ngOnInit(): void {
    this.http.get<ProfileResponse>('/profile').subscribe({
      next: (res) => this.userId.set(res.user_id),
      error: () => this.errorMessage.set('Could not load profile — try logging in again')
    });
  }

  logout(): void {
    this.auth.logout();
    this.router.navigateByUrl('/login');
  }
}
