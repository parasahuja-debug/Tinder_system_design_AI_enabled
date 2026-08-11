import { Component, inject, signal } from '@angular/core';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { AuthService } from '../auth.service';

// Register page. Purpose: create an account. auth_service's /auth/register
// also returns a token on success (see auth_service/main.py — "log the user
// straight in"), so a successful register lands on the same protected home
// page a login would, with no separate second login step.
@Component({
  selector: 'app-register',
  standalone: true,
  imports: [ReactiveFormsModule, RouterLink],
  templateUrl: './register.html'
})
export class Register {
  // inject() rather than constructor params — see login.ts for why (TS2729:
  // field initializers run before constructor-assigned params exist).
  private fb = inject(FormBuilder);
  private auth = inject(AuthService);
  private router = inject(Router);

  readonly errorMessage = signal<string | null>(null);
  readonly submitting = signal(false);

  readonly form = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(6)]]
  });

  submit(): void {
    if (this.form.invalid) return;

    this.errorMessage.set(null);
    this.submitting.set(true);

    this.auth.register(this.form.getRawValue()).subscribe({
      next: () => {
        this.submitting.set(false);
        this.router.navigateByUrl('/');
      },
      error: (err) => {
        this.submitting.set(false);
        // auth_service returns 409 specifically for a duplicate email.
        this.errorMessage.set(
          err.status === 409 ? 'That email is already registered' : 'Registration failed — please try again'
        );
      }
    });
  }
}
