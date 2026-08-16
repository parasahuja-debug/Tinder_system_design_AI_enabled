import { Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';

import { AuthService } from './auth.service';
import { SupportWidget } from './support-widget/support-widget';

// Root shell — routing (app.routes.ts) decides which page renders inside
// the <router-outlet/>. Each page (login/register/home) still owns its own
// state; the one exception, added here, is the support widget (below),
// which is global rather than page-scoped, so it has to mount at the shell
// level, not inside any one page.
// 2026-08-11: removed the CLI-generated `title` signal along with the
// welcome-page template that displayed it (see app.html.generated-placeholder).
@Component({
  selector: 'app-root',
  imports: [RouterOutlet, SupportWidget],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  // Gates the widget in app.html — a logged-out visitor (Login/Register)
  // has no X-User-Id for the WS handshake to authenticate, so there's
  // nothing useful the widget could do there anyway.
  protected auth = inject(AuthService);
}
