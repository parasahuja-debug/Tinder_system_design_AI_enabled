import { Component, OnInit, OnDestroy, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { ChatService, ChatMessage } from '../chat.service';
import { DiscoveryService } from '../discovery.service';
import { ProfileService } from '../profile.service';
import { AuthService } from '../auth.service';
import { BrandMark } from '../brand-mark/brand-mark';

type Mode = 'loading' | 'ready' | 'error';

// Chat — the live conversation for one match (behind authGuard, /chat/:matchId).
// Loads persisted history over plain HTTP, then opens a live WebSocket for
// anything sent from here on. See chat.service.ts and direct_msg/main.py's
// module docstring for why the WebSocket authenticates differently from
// every other request in this app.
@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [BrandMark, RouterLink, ReactiveFormsModule],
  templateUrl: './chat.html'
})
export class Chat implements OnInit, OnDestroy {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private fb = inject(FormBuilder);
  private chatService = inject(ChatService);
  private discoveryService = inject(DiscoveryService);
  private profileService = inject(ProfileService);
  private auth = inject(AuthService);

  private matchId!: string;
  private socket: WebSocket | null = null;

  readonly mode = signal<Mode>('loading');
  readonly messages = signal<ChatMessage[]>([]);
  // My own id, needed to tell "my message" from "their message" when
  // rendering — see chat.html's alignment. Fetched via ProfileService's
  // existing GET /profile rather than decoding the JWT client-side; its
  // response already carries user_id (see profile_service/main.py).
  readonly myUserId = signal<string | null>(null);
  readonly otherUserName = signal<string | null>(null);
  // Set when the socket closes for a reason the user should see — including
  // the real 4401/4403 codes direct_msg now sends (see direct_msg/main.py's
  // handshake rewrite), not just a generic "disconnected".
  readonly connectionError = signal<string | null>(null);

  readonly draft = this.fb.nonNullable.group({
    body: ['', Validators.required]
  });

  ngOnInit(): void {
    this.matchId = this.route.snapshot.paramMap.get('matchId')!;
    this.loadContext();
  }

  // Three dependent lookups before the page is useful: my own id (for
  // message alignment), which match this is + who the other participant is
  // (matcher_service's /matches only returns ids, same limitation Matches
  // page already works around), then that person's profile for the header.
  // Chained subscribes rather than RxJS composition operators, matching how
  // matches.ts already does its own multi-step per-row lookups.
  private loadContext(): void {
    this.mode.set('loading');
    this.profileService.getProfile().subscribe({
      next: (profile) => {
        this.myUserId.set(profile.user_id);
        this.discoveryService.listMatches().subscribe({
          next: (matches) => {
            const entry = matches.find((m) => m.match_id === this.matchId);
            if (!entry) {
              // Not one of the caller's own matches — same authorization
              // boundary direct_msg itself enforces server-side; this just
              // avoids showing a broken page instead of relying solely on
              // the eventual 403 from history/the socket.
              this.mode.set('error');
              return;
            }
            this.profileService.getProfileById(entry.other_user_id).subscribe({
              next: (otherProfile) => {
                this.otherUserName.set(otherProfile.name);
                this.loadHistoryAndConnect();
              },
              error: () => this.mode.set('error')
            });
          },
          error: () => this.mode.set('error')
        });
      },
      error: () => this.mode.set('error')
    });
  }

  // History first (what's already been said), then the live socket (what
  // gets said from now on) — in that order, so nothing sent the instant
  // after connecting could ever render before the backlog it belongs after.
  private loadHistoryAndConnect(): void {
    this.chatService.getHistory(this.matchId).subscribe({
      next: (history) => {
        this.messages.set(history);
        this.mode.set('ready');
        this.openSocket();
      },
      error: () => this.mode.set('error')
    });
  }

  private openSocket(): void {
    const socket = this.chatService.connect(this.matchId);
    this.socket = socket;

    socket.onmessage = (event) => {
      const message: ChatMessage = JSON.parse(event.data);
      this.messages.update((arr) => [...arr, message]);
    };

    socket.onclose = (event) => {
      this.socket = null;
      // Real, branchable close codes now that direct_msg accepts the
      // handshake before closing on an auth failure (see direct_msg/
      // main.py) — WS_AUTH_FAILED/WS_FORBIDDEN there, mirrored here.
      if (event.code === 4401) {
        this.connectionError.set('Your session expired — please log in again.');
      } else if (event.code === 4403) {
        this.connectionError.set('You are not part of this conversation.');
      } else if (event.code !== 1000) {
        // 1000 = normal closure (this page navigating away on purpose,
        // see ngOnDestroy/logout below) — anything else is unexpected.
        this.connectionError.set('Connection lost — reload the page to reconnect.');
      }
    };
  }

  send(): void {
    const body = this.draft.controls.body.value.trim();
    if (!body || !this.socket || this.socket.readyState !== WebSocket.OPEN) return;
    // No optimistic append here — the message only appears once direct_msg
    // echoes back the server-persisted copy over onmessage above, same
    // "trust the confirmed version, not the client's guess" reasoning as
    // the backend's own echo-to-sender behavior.
    this.socket.send(JSON.stringify({ body }));
    this.draft.reset({ body: '' });
  }

  logout(): void {
    this.socket?.close(1000, 'logout');
    this.auth.logout();
    this.router.navigateByUrl('/login');
  }

  ngOnDestroy(): void {
    // 1000 (normal closure) so the onclose handler above doesn't mistake
    // "I navigated away on purpose" for a real connection failure.
    this.socket?.close(1000, 'page left');
  }
}
