import { Injectable, inject } from '@angular/core';

import { AuthService } from './auth.service';

// Sent as the client's first WS message after connecting — decides which
// system prompt and which tools support_chatbot_service uses for this
// connection (see that service's CLAUDE.md). Not a security boundary:
// nothing sensitive becomes reachable in 'companion' mode that a 'faq' user
// couldn't already see elsewhere in the app, so the frontend safely owns
// this choice based on which page the widget was opened from.
export type SupportChatMode = 'faq' | 'companion';

// Shape received from support_chatbot_service's /support/ws (see
// support_chatbot_service/main.py's support_chat) — kept in sync manually,
// same as every other service's interface.
export interface SupportChatReply {
  reply: string;
}

// Owns talking to support_chatbot_service. Same "hand back a raw
// WebSocket, let the caller own its lifecycle" shape as ChatService's
// connect() — but unlike a match's Chat page (one connection for as long as
// that page is open), this widget opens a brand-new connection every time
// it's opened and closes it when it's closed: session = connection
// lifetime is the whole point of the in-session memory design (plan
// decision #7), not an implementation detail.
@Injectable({ providedIn: 'root' })
export class SupportChatService {
  private auth = inject(AuthService);

  // Opens the connection and sends the required {mode} handshake message
  // as soon as it's open — bundled into connect() itself, rather than left
  // for the widget component to remember, so the handshake support_
  // chatbot_service's WS endpoint requires can't accidentally be skipped or
  // sent out of order by a caller.
  connect(mode: SupportChatMode): WebSocket {
    // Same ws(s):// + subprotocol-token pattern as ChatService.connect() —
    // a WebSocket handshake can't carry an Authorization header at all,
    // which is why support_chatbot_service authenticates via the WS
    // subprotocol list instead (see its main.py's support_chat docstring).
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/support/ws`;
    const socket = new WebSocket(url, ['bearer', this.auth.getToken() ?? '']);

    socket.addEventListener(
      'open',
      () => socket.send(JSON.stringify({ mode })),
      { once: true },
    );

    return socket;
  }

  sendMessage(socket: WebSocket, message: string): void {
    socket.send(JSON.stringify({ message }));
  }
}
