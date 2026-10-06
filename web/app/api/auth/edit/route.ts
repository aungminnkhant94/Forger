import { NextRequest, NextResponse } from 'next/server';
import { createHash } from 'crypto';

export const runtime = 'nodejs';

const EDIT_MODE_KEY = (process.env.EDIT_MODE_KEY || process.env.NEXT_PUBLIC_EDIT_KEY || '').trim();
const BACKEND_DELETE_TOKEN = (process.env.BACKEND_DELETE_TOKEN || process.env.DELETE_API_TOKEN || process.env.NEXT_PUBLIC_EDIT_KEY || '').trim();
const EDIT_COOKIE = 'rolloforge_edit';
const AUTH_COOKIE = 'rolloforge_edit_auth';

function authCookieValue(): string {
  return createHash('sha256').update(`${EDIT_MODE_KEY}:${BACKEND_DELETE_TOKEN}`).digest('hex');
}

export async function POST(request: NextRequest) {
  if (!EDIT_MODE_KEY || !BACKEND_DELETE_TOKEN) {
    return NextResponse.json({ error: 'edit auth not configured' }, { status: 500 });
  }

  let payload: { key?: string } = {};
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: 'invalid request' }, { status: 400 });
  }

  if (!payload.key || payload.key !== EDIT_MODE_KEY) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  const response = NextResponse.json({ ok: true });
  const secure = request.nextUrl.protocol === 'https:';
  response.cookies.set(EDIT_COOKIE, '1', {
    httpOnly: false,
    sameSite: 'lax',
    secure,
    path: '/',
    maxAge: 60 * 60 * 24 * 30,
  });
  response.cookies.set(AUTH_COOKIE, authCookieValue(), {
    httpOnly: true,
    sameSite: 'lax',
    secure,
    path: '/',
    maxAge: 60 * 60 * 24 * 30,
  });
  return response;
}

export async function DELETE() {
  const response = NextResponse.json({ ok: true });
  response.cookies.delete(EDIT_COOKIE);
  response.cookies.delete(AUTH_COOKIE);
  return response;
}
