import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { NavigationStart, Router } from '@angular/router';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Subscription, filter } from 'rxjs';

import { SupportChatService, SupportChatMode, SupportChatReply } from '../support-chat.service';

interface DisplayMessage {
  role: 'user' | 'assistant';
  text: string;
}

// Global support-chat widget — mounted once in app.html (app.ts), floats on
// every authenticated page. Opens a brand-new WebSocket connection each
// time the panel is opened and closes it when the panel is closed: unlike
// chat.ts (one connection for as long as a match's Chat page stays open),
// the connection's lifetime *is* the chat session (plan decision #7) — no
// history is ever reloaded from a past session.
//
// Also closes automatically on every route navigation (decided after
// trying the alternative live — the widget persisting across pages — which
// left a stale mode active on whatever page the connection had originally
// opened on, e.g. still "faq" after navigating to Discover). Since this
// component is mounted outside <router-outlet/> in app.html, it would
// otherwise survive navigation entirely on its own — the NavigationStart
// subscription below is what makes it close instead.
@Component({
  selector: 'app-support-widget',
  standalone: true,
  imports: [ReactiveFormsModule],
  templateUrl: './support-widget.html'
})
export class SupportWidget implements OnInit, OnDestroy {
  private router = inject(Router);
  private fb = inject(FormBuilder);
  private supportChat = inject(SupportChatService);
  private navSubscription: Subscription | null = null;

  private socket: WebSocket | null = null;

  readonly isOpen = signal(false);
  readonly mode = signal<SupportChatMode>('faq');
  readonly messages = signal<DisplayMessage[]>([]);
  readonly connectionError = signal<string | null>(null);
  // True from the moment a message is sent until a reply (or a close/error)
  // arrives. Local-model replies genuinely take 10-40+ seconds, especially
  // in companion mode (two sequential model calls for the tool-call round
  // trip) — without this, a slow-but-working reply looks identical to
  // "stuck," which was exactly what prompted closing/reopening the widget
  // mid-response and never actually seeing a reply land.
  readonly isWaiting = signal(false);

  readonly draft = this.fb.nonNullable.group({
    text: ['', Validators.required]
  });

  ngOnInit(): void {
    // NavigationStart, not NavigationEnd: closes the moment a navigation is
    // initiated rather than waiting for it to finish, so the widget doesn't
    // sit open (mid-response, stale mode) while the next page is loading.
    this.navSubscription = this.router.events
      .pipe(filter((e) => e instanceof NavigationStart))
      .subscribe(() => {
        if (this.isOpen()) this.toggle();
      });
  }

  // Companion mode on Discover/Matches/Chat (where match data is actually
  // relevant and a user is most likely to want supportive framing); faq
  // everywhere else. Not a permission check — see support_chatbot_service/
  // CLAUDE.md's Modes section for why this is safe for the frontend to
  // decide unilaterally.
  private resolveMode(): SupportChatMode {
    const url = this.router.url;
    const isCompanionRoute =
      url.startsWith('/discover') || url.startsWith('/matches') || url.startsWith('/chat');
    return isCompanionRoute ? 'companion' : 'faq';
  }

  toggle(): void {
    if (this.isOpen()) {
      this.closeSocket(1000, 'panel closed');
      this.isOpen.set(false);
      return;
    }

    // Fresh state every open — no carry-over from a previous open/close of
    // this same widget instance, matching "starts fresh the next time".
    this.messages.set([]);
    this.connectionError.set(null);
    this.isWaiting.set(false);
    this.mode.set(this.resolveMode());
    this.isOpen.set(true);
    this.openSocket();
  }

  private openSocket(): void {
    const socket = this.supportChat.connect(this.mode());
    this.socket = socket;

    socket.onmessage = (event) => {
      const data: SupportChatReply = JSON.parse(event.data);
      this.messages.update((arr) => [...arr, { role: 'assistant', text: data.reply }]);
      this.isWaiting.set(false);
    };

    socket.onclose = (event) => {
      this.socket = null;
      this.isWaiting.set(false); // don't leave the indicator spinning forever if the connection drops mid-reply
      // Real, branchable close codes from support_chatbot_service's
      // support_chat handshake (main.py) — mirrors chat.ts's handling of
      // direct_msg's close codes, different numeric meanings per service.
      if (event.code === 4401) {
        this.connectionError.set('Your session expired — please log in again.');
      } else if (event.code === 4400) {
        this.connectionError.set('Could not start the chat — please try reopening it.');
      } else if (event.code !== 1000) {
        this.connectionError.set('Connection lost — try closing and reopening the chat.');
      }
    };
  }

  send(): void {
    const text = this.draft.controls.text.value.trim();
    // isWaiting blocks a second send before the first reply lands — the
    // template also disables the form while waiting, this is the
    // programmatic backstop (e.g. against an Enter-key submit racing a
    // click).
    if (!text || !this.socket || this.socket.readyState !== WebSocket.OPEN || this.isWaiting()) return;

    // Appended immediately, not on server echo: unlike direct_msg, support_
    // chatbot_service's protocol only ever sends {"reply": ...} back — there
    // is no second human who needs an authoritative persisted copy of what
    // was sent, so there's nothing to wait for here.
    this.messages.update((arr) => [...arr, { role: 'user', text }]);
    this.supportChat.sendMessage(this.socket, text);
    this.draft.reset({ text: '' });
    this.isWaiting.set(true);
  }

  private closeSocket(code: number, reason: string): void {
    this.socket?.close(code, reason);
    this.socket = null;
  }

  ngOnDestroy(): void {
    // 1000 (normal closure) — e.g. logout tearing down the whole app shell.
    this.closeSocket(1000, 'widget destroyed');
    this.navSubscription?.unsubscribe();
  }
}
