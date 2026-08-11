import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

// Root shell — routing (app.routes.ts) decides which page renders inside
// the <router-outlet/>. No app-level state lives here on purpose; each page
// (login/register/home) owns its own.
// 2026-08-11: removed the CLI-generated `title` signal along with the
// welcome-page template that displayed it (see app.html.generated-placeholder).
@Component({
  selector: 'app-root',
  imports: [RouterOutlet],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {}
