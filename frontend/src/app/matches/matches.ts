import { Component, OnInit, OnDestroy, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { DiscoveryService, MatchEntry } from '../discovery.service';
import { ProfileService } from '../profile.service';
import { AuthService } from '../auth.service';
import { BrandMark } from '../brand-mark/brand-mark';

type Mode = 'loading' | 'ready' | 'empty' | 'error';

// One row on the list. name/age/city/photoUrl start null and fill in as
// getProfileById/listImagesForUser resolve — the row exists (in the right,
// newest-first order from GET /matches) before its details do, so the list
// doesn't jitter/reorder as different matches' lookups resolve at different
// speeds.
interface MatchDisplay {
  match_id: string;
  other_user_id: string;
  name: string | null;
  age: number | null;
  city: string | null;
  photoUrl: string | null;
}

// Matches — the list of everyone the caller has mutually liked (behind
// authGuard, /matches). matcher_service's own /matches only returns ids;
// this component enriches each row with that user's profile + first photo.
@Component({
  selector: 'app-matches',
  standalone: true,
  imports: [BrandMark, RouterLink],
  templateUrl: './matches.html'
})
export class Matches implements OnInit, OnDestroy {
  private discoveryService = inject(DiscoveryService);
  private profileService = inject(ProfileService);
  private auth = inject(AuthService);
  private router = inject(Router);

  readonly mode = signal<Mode>('loading');
  readonly matches = signal<MatchDisplay[]>([]);

  ngOnInit(): void {
    this.loadMatches();
  }

  private loadMatches(): void {
    this.mode.set('loading');
    this.discoveryService.listMatches().subscribe({
      next: (entries) => {
        if (entries.length === 0) {
          this.mode.set('empty');
          return;
        }
        this.mode.set('ready');
        // Placeholder rows first, in the server's order — see MatchDisplay's
        // write-up above for why this is separate from the detail fetches.
        this.matches.set(
          entries.map((e) => ({
            match_id: e.match_id,
            other_user_id: e.other_user_id,
            name: null,
            age: null,
            city: null,
            photoUrl: null
          }))
        );
        entries.forEach((entry) => this.loadMatchDetails(entry));
      },
      error: () => this.mode.set('error')
    });
  }

  // Fetches one match's profile, updates its row in place (matched by
  // match_id, not array index — index would drift if rows ever get added/
  // removed), then kicks off the photo fetch. A failed profile lookup for
  // one match is left as a permanently-blank row rather than failing the
  // whole page — matches the "one bad candidate shouldn't break the batch"
  // reasoning already used in Discover.
  private loadMatchDetails(entry: MatchEntry): void {
    this.profileService.getProfileById(entry.other_user_id).subscribe({
      next: (profile) => {
        this.matches.update((arr) =>
          arr.map((m) =>
            m.match_id === entry.match_id ? { ...m, name: profile.name, age: profile.age, city: profile.city } : m
          )
        );
        this.loadFirstPhoto(entry.other_user_id, entry.match_id);
      }
    });
  }

  // Only the first photo — this is a list row, not a full profile view, so
  // there's no gallery here the way Home/Discover have one.
  private loadFirstPhoto(userId: string, matchId: string): void {
    this.profileService.listImagesForUser(userId).subscribe({
      next: (metas) => {
        if (metas.length === 0) return;
        this.profileService.getImageBlob(metas[0].image_id).subscribe({
          next: (blob) => {
            const objectUrl = URL.createObjectURL(blob);
            this.matches.update((arr) => arr.map((m) => (m.match_id === matchId ? { ...m, photoUrl: objectUrl } : m)));
          }
        });
      }
    });
  }

  // Same as Home/Discover's logout — repeated rather than shared, same
  // reasoning as Discover's copy (no common page-shell yet).
  logout(): void {
    this.auth.logout();
    this.router.navigateByUrl('/login');
  }

  ngOnDestroy(): void {
    this.matches().forEach((m) => {
      if (m.photoUrl) URL.revokeObjectURL(m.photoUrl);
    });
  }
}
