import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { AuthService } from './auth.service';

// Shape returned by direct_msg's GET /chat/history/{match_id} and pushed
// over the WebSocket (see direct_msg/main.py's Message model + payload
// shape) — kept in sync manually, same as every other service's interface.
export interface ChatMessage {
  id: string;
  match_id: string;
  sender_id: string;
  body: string;
  created_at: string;
}

// Owns talking to direct_msg. Same pattern as DiscoveryService/ProfileService
// for the plain-HTTP history fetch, but connect() is different in kind: it
// hands back a raw WebSocket instead of an Observable, because the chat
// component needs to own the socket's lifecycle itself (open on page enter,
// close on page leave) — see chat/chat.ts.
@Injectable({ providedIn: 'root' })
export class ChatService {
  private http = inject(HttpClient);
  private auth = inject(AuthService);

  getHistory(matchId: string): Observable<ChatMessage[]> {
    return this.http.get<ChatMessage[]>(`/chat/history/${matchId}`);
  }

  // Opens the live chat connection for one match. Unlike every other call in
  // this app, this doesn't go through HttpClient (and therefore not through
  // auth.interceptor.ts either) — a WebSocket handshake can't carry an
  // Authorization header at all, which is the whole reason direct_msg
  // authenticates via the WS subprotocol list instead (see direct_msg/
  // main.py's module docstring). ['bearer', token] here is the client side
  // of that same convention: it becomes the Sec-WebSocket-Protocol header on
  // the handshake request.
  connect(matchId: string): WebSocket {
    // ws:// in dev (proxied by proxy.conf.json's "ws": true entry to the
    // gateway); wss:// only if the page itself was loaded over https, so
    // this keeps working unmodified behind a real TLS-terminating deploy.
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/chat/ws/${matchId}`;
    return new WebSocket(url, ['bearer', this.auth.getToken() ?? '']);
  }
}
