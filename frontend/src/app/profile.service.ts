import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

// Shape returned by profile_service's GET/POST/PUT /profile (see
// profile_service/main.py) — kept in sync manually since there's no shared
// schema between frontend and backend yet.
export interface Profile {
  user_id: string;
  name: string;
  age: number;
  gender: string;
  state: string;
  city: string;
  lat: number;
  long: number;
  bio: string;
}

// Body shape for create/update. No user_id field on purpose — same rule as
// profile_service's ProfileRequest: identity comes from the gateway's
// X-User-Id header, never from client-supplied data.
export type ProfileRequest = Omit<Profile, 'user_id'>;

// Shape returned by GET /profile/{user_id} — deliberately missing lat/long
// compared to Profile above (see profile_service/main.py's
// get_profile_by_id: exact coordinates are more sensitive than a match
// needs to see).
export type PublicProfile = Omit<Profile, 'lat' | 'long'>;

interface ProfileWriteResponse {
  message: string;
  user_id: string;
}

// Shape returned by image_service's POST/GET /images (see
// image_service/main.py) — metadata only, never the actual image bytes.
export interface ImageMeta {
  image_id: string;
  url: string;
  original_filename: string;
}

// Owns talking to profile_service. Same pattern as AuthService: pages read
// profile data through this service rather than calling HttpClient directly,
// so the route paths/shapes only live in one place.
@Injectable({ providedIn: 'root' })
export class ProfileService {
  constructor(private http: HttpClient) {}

  // 404s if the user hasn't created a profile yet — callers branch on that,
  // not on some separate "exists" flag, matching how profile_service itself
  // signals "no profile" (see profile_service/main.py GET /profile).
  getProfile(): Observable<Profile> {
    return this.http.get<Profile>('/profile');
  }

  createProfile(profile: ProfileRequest): Observable<ProfileWriteResponse> {
    return this.http.post<ProfileWriteResponse>('/profile', profile);
  }

  updateProfile(profile: ProfileRequest): Observable<ProfileWriteResponse> {
    return this.http.put<ProfileWriteResponse>('/profile', profile);
  }

  // Metadata only (id + url) — never the image bytes themselves. Used to
  // render the list of thumbnails; each thumbnail's actual pixels are
  // fetched separately via getImageBlob.
  listImages(): Observable<ImageMeta[]> {
    return this.http.get<ImageMeta[]>('/images');
  }

  // Another user's profile — used on the Matches page, so each side can see
  // who they matched with. 404s if that user somehow has no profile.
  getProfileById(userId: string): Observable<PublicProfile> {
    return this.http.get<PublicProfile>(`/profile/${userId}`);
  }

  // Another user's image metadata — same Matches-page use case as
  // getProfileById above.
  listImagesForUser(userId: string): Observable<ImageMeta[]> {
    return this.http.get<ImageMeta[]>(`/images/user/${userId}`);
  }

  // FormData, not JSON: image_service's /images route expects
  // multipart/form-data (it parses the body with FastAPI's UploadFile/File,
  // which needs python-multipart on the backend). Angular auto-generates the
  // correct multipart Content-Type + boundary when the body is a FormData
  // instance — never set Content-Type manually here, it would break the
  // boundary the server expects.
  uploadImage(file: File): Observable<ImageMeta> {
    const formData = new FormData();
    formData.append('file', file);
    return this.http.post<ImageMeta>('/images', formData);
  }

  // responseType: 'blob' — GET /images/<id> returns raw image bytes, not
  // JSON, so HttpClient's default JSON parsing would fail on it. Goes
  // through this same HttpClient (and therefore the auth interceptor)
  // specifically so <img> tags never have to make their own unauthenticated
  // request — see the write-up on why a plain <img src="/images/id"> can't
  // carry the Authorization header.
  getImageBlob(imageId: string): Observable<Blob> {
    return this.http.get(`/images/${imageId}`, { responseType: 'blob' });
  }
}
