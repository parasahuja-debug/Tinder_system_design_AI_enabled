import { Routes } from '@angular/router';

import { authGuard } from './auth.guard';

// One route per page, per repo convention (CLAUDE.md: "Angular app, one page
// per feature"). '/' is the protected landing page; unauthenticated visitors
// are bounced to /login by authGuard. Unknown paths redirect home rather than
// 404ing, since the guard will redirect further to /login if needed.
export const routes: Routes = [
  {
    path: '',
    loadComponent: () => import('./home/home').then((m) => m.Home),
    canActivate: [authGuard]
  },
  {
    path: 'discover',
    loadComponent: () => import('./discover/discover').then((m) => m.Discover),
    canActivate: [authGuard]
  },
  {
    path: 'matches',
    loadComponent: () => import('./matches/matches').then((m) => m.Matches),
    canActivate: [authGuard]
  },
  {
    path: 'login',
    loadComponent: () => import('./login/login').then((m) => m.Login)
  },
  {
    path: 'register',
    loadComponent: () => import('./register/register').then((m) => m.Register)
  },
  { path: '**', redirectTo: '' }
];
