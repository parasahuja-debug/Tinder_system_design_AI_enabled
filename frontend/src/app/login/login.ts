import { Component, inject, signal } from '@angular/core';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { AuthService } from '../auth.service';
import { BrandMark } from '../brand-mark/brand-mark';

// Login page. Purpose: collect email/password, exchange them for a JWT via
// AuthService, and land the user on the protected home page. Errors from the
// API (401 on wrong credentials) are surfaced inline rather than thrown, so a
// bad login doesn't look like a crash.
@Component({
  selector: 'app-login',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink, BrandMark],
  templateUrl: './login.html'
})
export class Login {
  // inject() rather than constructor params: field initializers (the `form`
  // below) run before the constructor body, so a constructor-injected `fb`
  // would still be undefined when `form` is built (TS2729).
  private fb = inject(FormBuilder);
  private auth = inject(AuthService);
  private router = inject(Router);

  readonly errorMessage = signal<string | null>(null);
  readonly submitting = signal(false);

  readonly form = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', Validators.required]
  });

  submit(): void {
    if (this.form.invalid) return;

    this.errorMessage.set(null);
    this.submitting.set(true);

    this.auth.login(this.form.getRawValue()).subscribe({
      next: () => {
        this.submitting.set(false);
        this.router.navigateByUrl('/');
      },
      error: (err) => {
        this.submitting.set(false);
        // auth_service returns a generic 401 for both unknown-email and
        // wrong-password (see auth_service/main.py) — mirror that generic
        // framing here rather than guessing at a more specific cause.
        this.errorMessage.set(
          err.status === 401 ? 'Invalid email or password' : 'Login failed — please try again'
        );
      }
    });
  }
}
