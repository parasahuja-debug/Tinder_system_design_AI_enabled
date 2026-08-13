import { Component, OnInit, OnDestroy, inject, signal, computed } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { DiscoveryService, Candidate } from '../discovery.service';
import { ProfileService } from '../profile.service';
import { AuthService } from '../auth.service';
import { BrandMark } from '../brand-mark/brand-mark';

type Mode = 'loading' | 'ready' | 'empty' | 'error';

// Pairs an image's id with a browser-local object URL — same pattern as
// Home's DisplayImage (see home.ts), needed for the same reason: photos are
// fetched as authenticated blobs through ProfileService.getImageBlob, not
// via a plain <img src> (the gateway needs the JWT in an Authorization
// header, which a bare <img> tag can't send).
interface DisplayImage {
  image_id: string;
  objectUrl: string;
}

// Discover — the swipe deck (behind authGuard, /discover). Fetches a batch
// of nearby, not-yet-swiped candidates from recommendation_service on load,
// shows one at a time, and records each decision via matcher_service.
@Component({
  selector: 'app-discover',
  standalone: true,
  imports: [BrandMark, RouterLink],
  templateUrl: './discover.html'
})
export class Discover implements OnInit, OnDestroy {
  private discoveryService = inject(DiscoveryService);
  private profileService = inject(ProfileService);
  private auth = inject(AuthService);
  private router = inject(Router);

  readonly mode = signal<Mode>('loading');
  readonly candidates = signal<Candidate[]>([]);
  // The card currently on screen is always the front of the queue — swiping
  // just drops the front element (see swipe() below), so there's no
  // separate "current index" to keep in sync with the array.
  readonly current = computed(() => this.candidates()[0] ?? null);

  readonly currentImages = signal<DisplayImage[]>([]);
  readonly swiping = signal(false);
  // Set only if the POST /swipe request itself fails (network/backend
  // error) — the decision was never recorded, so the candidate stays on
  // screen rather than silently advancing as if it had gone through.
  readonly errorMessage = signal<string | null>(null);
  // Non-null briefly after a mutual match, holding the matched name for the
  // "It's a match!" banner — cleared when the user dismisses it or the next
  // card loads.
  readonly matchName = signal<string | null>(null);

  ngOnInit(): void {
    this.loadCandidates();
  }

  private loadCandidates(): void {
    this.mode.set('loading');
    this.discoveryService.discover().subscribe({
      next: (candidates) => {
        this.candidates.set(candidates);
        this.mode.set(candidates.length > 0 ? 'ready' : 'empty');
        if (candidates.length > 0) this.loadImagesForCurrent();
      },
      error: () => this.mode.set('error')
    });
  }

  // Re-runs the same /discover query — used by the "Check again" button in
  // the empty state, since new candidates may exist later (someone else
  // created a profile nearby) even though none did a moment ago.
  refresh(): void {
    this.loadCandidates();
  }

  // Fetches the bytes for whichever candidate is now at the front of the
  // queue. Always clears + revokes the previous candidate's object URLs
  // first — otherwise each swipe would leak the prior card's blob URLs and,
  // worse, briefly show the old photos under the new candidate's name while
  // the new fetch is still in flight.
  private loadImagesForCurrent(): void {
    this.currentImages().forEach((img) => URL.revokeObjectURL(img.objectUrl));
    this.currentImages.set([]);

    const candidate = this.current();
    if (!candidate) return;

    for (const imageId of candidate.image_ids) {
      this.profileService.getImageBlob(imageId).subscribe({
        next: (blob) => {
          const objectUrl = URL.createObjectURL(blob);
          this.currentImages.update((imgs) => [...imgs, { image_id: imageId, objectUrl }]);
        }
      });
    }
  }

  // Records the caller's decision on the current candidate, then advances.
  // Guarded by `swiping` so a slow request can't be double-submitted by a
  // second click before the first one resolves.
  swipeAction(direction: 'like' | 'pass'): void {
    const candidate = this.current();
    if (!candidate || this.swiping()) return;

    this.errorMessage.set(null);
    this.swiping.set(true);

    this.discoveryService.swipe(candidate.user_id, direction).subscribe({
      next: (result) => {
        this.swiping.set(false);
        // Hold the name for the match banner — advance() below still runs,
        // so the deck keeps moving underneath the banner rather than
        // blocking on it (dismissMatch() just clears the banner text).
        if (result.matched) this.matchName.set(candidate.name);
        this.advance();
      },
      error: () => {
        this.swiping.set(false);
        this.errorMessage.set('Could not record that — please try again.');
      }
    });
  }

  dismissMatch(): void {
    this.matchName.set(null);
  }

  // Drops the just-decided candidate off the front of the queue and loads
  // the next one's photos — or, if that was the last one, switches to the
  // empty state and releases the now-stale image URLs.
  private advance(): void {
    this.candidates.update((arr) => arr.slice(1));
    if (this.candidates().length === 0) {
      this.mode.set('empty');
      this.currentImages().forEach((img) => URL.revokeObjectURL(img.objectUrl));
      this.currentImages.set([]);
    } else {
      this.loadImagesForCurrent();
    }
  }

  // Same as Home's logout — repeated here rather than shared, since these
  // are separate standalone components with no common page-shell yet.
  logout(): void {
    this.auth.logout();
    this.router.navigateByUrl('/login');
  }

  ngOnDestroy(): void {
    this.currentImages().forEach((img) => URL.revokeObjectURL(img.objectUrl));
  }
}
