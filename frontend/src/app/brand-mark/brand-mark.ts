import { Component, Input } from '@angular/core';

// Shared brand identity — the "Mutual" wordmark + two-figure/heart icon.
// Used on login, register, and (compact) the profile page. Extracted into
// its own component once a third usage site came up — duplicating the SVG
// markup a third time across templates would have been the wrong call.
@Component({
  selector: 'app-brand-mark',
  standalone: true,
  templateUrl: './brand-mark.html'
})
export class BrandMark {
  // 'full': icon + name + tagline, centered, large — landing-style pages
  // (login/register). 'compact': small icon + name only, inline — a
  // functional page (Home) doesn't need the full first-impression treatment
  // every time, just a persistent reminder of what app this is.
  @Input() variant: 'full' | 'compact' = 'full';
  @Input() tagline = '';
}
