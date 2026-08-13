import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

// Shape returned by recommendation_service's GET /discover (see
// recommendation_service/main.py) — kept in sync manually, same as
// ProfileService's Profile interface.
export interface Candidate {
  user_id: string;
  name: string;
  age: number;
  gender: string;
  city: string;
  bio: string;
  image_ids: string[];
}

// Body shape for matcher_service's POST /swipe. No swiper id field — same
// rule as everywhere else: identity comes from the gateway's X-User-Id
// header, never from client-supplied data.
export interface SwipeRequest {
  target_id: string;
  direction: 'like' | 'pass';
}

export interface SwipeResult {
  message: string;
  matched: boolean;
}

// Shape returned by matcher_service's GET /matches.
export interface MatchEntry {
  match_id: string;
  other_user_id: string;
  created_at: string;
}

// Owns talking to recommendation_service and matcher_service. Same pattern
// as ProfileService: pages read/write through this service rather than
// calling HttpClient directly, so the route paths/shapes only live here.
@Injectable({ providedIn: 'root' })
export class DiscoveryService {
  constructor(private http: HttpClient) {}

  // No query params sent from here — recommendation_service defaults
  // radius/limit itself, and min_age/max_age/gender stay unsent (unfiltered)
  // until a future filter UI decides to pass them (see IDEAS.md).
  discover(): Observable<Candidate[]> {
    return this.http.get<Candidate[]>('/discover');
  }

  swipe(targetId: string, direction: 'like' | 'pass'): Observable<SwipeResult> {
    return this.http.post<SwipeResult>('/swipe', { target_id: targetId, direction });
  }

  listMatches(): Observable<MatchEntry[]> {
    return this.http.get<MatchEntry[]>('/matches');
  }
}
