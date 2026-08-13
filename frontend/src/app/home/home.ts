import { Component, OnInit, OnDestroy, inject, signal, computed } from '@angular/core';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
// 2026-08-13: no longer used directly — calls now go through ProfileService
// instead, same as AuthService already does for auth calls. Kept for
// history per standing rule:
// import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';

import { AuthService } from '../auth.service';
import { ProfileService, ProfileRequest, ImageMeta } from '../profile.service';
import { INDIA_STATES, INDIA_STATES_AND_CITIES } from '../india-locations';
import { BrandMark } from '../brand-mark/brand-mark';

// 2026-08-13: replaced — this was the Day 1 stub's response shape (just
// user_id + a message echoing it back). The real Profile type now lives in
// profile.service.ts, since ProfileService owns talking to profile_service.
// Kept for history per standing rule:
// interface ProfileResponse {
//   user_id: string;
//   message: string;
// }

type Mode = 'loading' | 'create' | 'edit';

// Pairs an image's id with a browser-local object URL created from its blob
// (see ProfileService.getImageBlob) — objectUrl is what the template's
// <img [src]> actually binds to; it's never a real network URL.
interface DisplayImage {
  image_id: string;
  objectUrl: string;
}

// The protected landing page (behind authGuard) — repurposed from the Day 1
// auth-verification stub into the real profile create/edit page. On load it
// calls GET /profile: a 404 means the user hasn't created one yet (create
// mode, empty form), a 200 means they have (edit mode, form pre-filled).
@Component({
  selector: 'app-home',
  standalone: true,
  imports: [ReactiveFormsModule, BrandMark],
  templateUrl: './home.html'
})
export class Home implements OnInit, OnDestroy {
  // 2026-08-13: replaced — userId no longer needed (the stub just echoed it
  // back). Constructor injection replaced by inject() below, same reason as
  // Login: the `form` field initializer runs before the constructor body
  // would, so a constructor-injected `fb` would still be undefined (TS2729).
  // Kept for history per standing rule:
  // readonly userId = signal<string | null>(null);
  //
  // constructor(
  //   private http: HttpClient,
  //   private auth: AuthService,
  //   private router: Router
  // ) {}
  private fb = inject(FormBuilder);
  private profileService = inject(ProfileService);
  private auth = inject(AuthService);
  private router = inject(Router);

  readonly mode = signal<Mode>('loading');
  readonly errorMessage = signal<string | null>(null);
  readonly submitting = signal(false);
  readonly saved = signal(false);

  // Each entry pairs an image's id with a browser-local object URL (see
  // getImageBlob's write-up) — the objectUrl is what <img [src]> actually binds to.
  readonly images = signal<DisplayImage[]>([]);
  readonly uploadingImage = signal(false);
  readonly imageError = signal<string | null>(null);

  // 2026-08-13: replaced — lat/long used to be manual number inputs on this
  // form. They're now auto-filled from the browser's geolocation instead
  // (see captureLocation below) and held as plain signals, not form
  // controls, since the user never types them. Kept for history per
  // standing rule:
  // lat: [0, Validators.required],
  // long: [0, Validators.required],
  readonly lat = signal<number | null>(null);
  readonly long = signal<number | null>(null);
  readonly locationError = signal<string | null>(null);

  readonly INDIA_STATES = INDIA_STATES;

  // age >= 18: a dating-app profile below that isn't a valid state, checked
  // client-side same as every other required field. bio capped at 500 —
  // dating-app bios are meant to be short; the limit is enforced here and
  // mirrored as a maxlength in the template so the user sees it, not just
  // gets silently blocked.
  readonly form = this.fb.nonNullable.group({
    name: ['', Validators.required],
    age: [18, [Validators.required, Validators.min(18)]],
    gender: ['', Validators.required],
    state: ['', Validators.required],
    city: ['', Validators.required],
    bio: ['', [Validators.required, Validators.maxLength(500)]]
  });

  // Cities depend on the currently-selected state — read live off the form
  // rather than cached, so the dropdown updates the moment the state changes.
  citiesForState(): string[] {
    const state = this.form.controls.state.value;
    return state ? (INDIA_STATES_AND_CITIES[state] ?? []) : [];
  }

  // 2026-08-13: replaced — old body just echoed the stub's user_id back to
  // prove the auth chain worked; now branches on whether a real profile
  // exists yet. Kept for history per standing rule:
  // ngOnInit(): void {
  //   this.http.get<ProfileResponse>('/profile').subscribe({
  //     next: (res) => this.userId.set(res.user_id),
  //     error: () => this.errorMessage.set('Could not load profile — try logging in again')
  //   });
  // }
  ngOnInit(): void {
    this.profileService.getProfile().subscribe({
      next: (profile) => {
        this.mode.set('edit');
        this.form.patchValue(profile);
        // 2026-08-13: fixed — this used to reuse profile.lat/profile.long
        // from the stored row instead of asking the browser again, reasoning
        // "no need to re-prompt for permission." That reasoning was wrong:
        // getCurrentPosition() doesn't show a new permission dialog once the
        // browser already granted it for this origin — it just silently
        // returns the current reading. Reusing the old value meant location
        // could go stale indefinitely, which matters for Day 3's
        // location-based matching. Now every load re-captures fresh.
        this.captureLocation();
        this.loadImages();
      },
      error: (err) => {
        if (err.status === 404) {
          // Expected state for a new user, not a real error — just means
          // the create form should start empty.
          this.mode.set('create');
          this.captureLocation();
        } else {
          this.errorMessage.set('Could not load profile — try logging in again');
        }
      }
    });
  }

  // Requests the browser's geolocation once and stores it in the lat/long
  // signals. Not a form control: the user never types this, so there's
  // nothing for Angular's form validity to track here — locationError is
  // what submit() checks instead. No fallback source if permission is
  // denied (no city-based estimate) — retryLocation() just asks again.
  private captureLocation(): void {
    if (!navigator.geolocation) {
      this.locationError.set('Your browser does not support location — cannot continue without it.');
      return;
    }
    this.locationError.set(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        this.lat.set(pos.coords.latitude);
        this.long.set(pos.coords.longitude);
        this.locationError.set(null);
      },
      () => {
        this.locationError.set('Location access is needed to create your profile. Please allow it and try again.');
      }
    );
  }

  retryLocation(): void {
    this.captureLocation();
  }

  // The city dropdown's options depend on the selected state — if the state
  // changes, whatever city was previously selected likely doesn't belong to
  // the new state's list, so it's cleared rather than left dangling.
  onStateChange(): void {
    this.form.controls.city.setValue('');
  }

  readonly justCreated = signal(false);

  // The "Next: Discover" step only unlocks once there's a profile AND at
  // least one photo — showing up with zero photos to swipe on is a worse
  // first impression than not being able to browse yet, so this gate exists
  // deliberately, not just as a loading-state check.
  readonly canDiscover = computed(() => this.mode() === 'edit' && this.images().length > 0);

  goToDiscover(): void {
    this.router.navigateByUrl('/discover');
  }

  submit(): void {
    if (this.form.invalid) return;

    // lat/long come from geolocation, not the form — if it never resolved
    // (denied/unsupported), there's nothing valid to submit.
    const lat = this.lat();
    const long = this.long();
    if (lat === null || long === null) {
      this.locationError.set('Location access is needed to create your profile. Please allow it and try again.');
      return;
    }

    this.errorMessage.set(null);
    this.saved.set(false);
    this.submitting.set(true);

    const wasCreate = this.mode() === 'create';
    const body: ProfileRequest = { ...this.form.getRawValue(), lat, long };
    const request$ = wasCreate
      ? this.profileService.createProfile(body)
      : this.profileService.updateProfile(body);

    request$.subscribe({
      next: () => {
        this.submitting.set(false);
        this.saved.set(true);
        this.mode.set('edit'); // a successful create moves straight into edit mode
        this.form.markAsPristine(); // "Save changes" goes back to disabled until the next real edit

        if (wasCreate) {
          // 2026-08-13: the photo panel is now always visible adjacent to
          // the form (see home.html), just disabled until the profile
          // exists — no need to scroll to it anymore, it's already on
          // screen. justCreated now only drives a brief highlight to mark
          // the moment it becomes unlocked.
          this.justCreated.set(true);
        }
      },
      error: () => {
        this.submitting.set(false);
        this.errorMessage.set('Could not save profile — please try again');
      }
    });
  }

  logout(): void {
    this.auth.logout();
    this.router.navigateByUrl('/login');
  }

  // Fetches this user's image metadata, then the actual bytes for each one.
  // Clears + revokes any previously loaded object URLs first — a cheap guard
  // that keeps this safe to call more than once without leaking memory or
  // duplicating entries, even though today it's only ever called from
  // ngOnInit's edit-mode branch.
  private loadImages(): void {
    this.images().forEach((img) => URL.revokeObjectURL(img.objectUrl));
    this.images.set([]);

    this.profileService.listImages().subscribe({
      next: (metas) => metas.forEach((meta) => this.fetchAndStoreImage(meta))
    });
  }

  private fetchAndStoreImage(meta: ImageMeta): void {
    this.profileService.getImageBlob(meta.image_id).subscribe({
      next: (blob) => {
        const objectUrl = URL.createObjectURL(blob);
        this.images.update((imgs) => [...imgs, { image_id: meta.image_id, objectUrl }]);
      }
    });
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;

    this.imageError.set(null);
    this.uploadingImage.set(true);
    this.justCreated.set(false); // the user found the section; stop highlighting it

    this.profileService.uploadImage(file).subscribe({
      next: (meta) => {
        this.uploadingImage.set(false);
        this.fetchAndStoreImage(meta);
        // Reset the input so selecting the exact same file again still
        // fires a 'change' event (the browser otherwise treats it as
        // unchanged and won't re-emit).
        input.value = '';
      },
      error: (err) => {
        this.uploadingImage.set(false);
        // err.error?.detail is profile_service/image_service's specific
        // reason (bad extension, size limit, cap reached, duplicate
        // filename — see image_service/main.py). status === 0 means the
        // request never reached the server at all (network/CORS failure),
        // which has no .detail to show — a distinct, actionable message for
        // that case beats a blank/generic one.
        if (err.status === 0) {
          this.imageError.set('Could not reach the server — check your connection and try again.');
        } else {
          this.imageError.set(err.error?.detail ?? 'Upload failed — please try again.');
        }
      }
    });
  }

  ngOnDestroy(): void {
    // Release every object URL created for this page — otherwise each one
    // stays pinned in browser memory until the whole tab closes, even after
    // this component is gone.
    this.images().forEach((img) => URL.revokeObjectURL(img.objectUrl));
  }
}
