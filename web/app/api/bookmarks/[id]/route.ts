import { NextRequest, NextResponse } from 'next/server';
import { createHash } from 'crypto';

export const runtime = 'nodejs';

const BACKEND_URL = (process.env.DELETE_API_URL || '').trim();
const EDIT_MODE_KEY = (process.env.EDIT_MODE_KEY || process.env.NEXT_PUBLIC_EDIT_KEY || '').trim();
const BACKEND_DELETE_TOKEN = (process.env.BACKEND_DELETE_TOKEN || process.env.DELETE_API_TOKEN || process.env.NEXT_PUBLIC_EDIT_KEY || '').trim();
const EDIT_COOKIE = 'rolloforge_edit';
const AUTH_COOKIE = 'rolloforge_edit_auth';

function expectedAuthCookie(): string {
  return createHash('sha256').update(`${EDIT_MODE_KEY}:${BACKEND_DELETE_TOKEN}`).digest('hex');
}

export async function DELETE(
  request: NextRequest,
  context: { params: Promise<{ id: string }> }
) {
  const { id } = await context.params;
  const editCookie = request.cookies.get(EDIT_COOKIE)?.value || '';
  const authCookie = request.cookies.get(AUTH_COOKIE)?.value || '';

  if (!id) {
    return NextResponse.json({ error: 'missing bookmark id' }, { status: 400 });
  }

  if (!BACKEND_URL) {
    return NextResponse.json({ error: 'delete backend not configured (set DELETE_API_URL)' }, { status: 501 });
  }

  if (!EDIT_MODE_KEY || !BACKEND_DELETE_TOKEN) {
    return NextResponse.json({ error: 'delete route not configured' }, { status: 500 });
  }

  if (editCookie !== '1' || authCookie !== expectedAuthCookie()) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  try {
    const upstream = await fetch(`${BACKEND_URL}/api/bookmarks/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: {
        Authorization: `Bearer ${BACKEND_DELETE_TOKEN}`,
      },
      cache: 'no-store',
    });

    const text = await upstream.text();
    let data: unknown = { ok: upstream.ok };

    try {
      data = text ? JSON.parse(text) : data;
    } catch {
      data = { ok: upstream.ok, raw: text };
    }

    return NextResponse.json(data, { status: upstream.status });
  } catch (error) {
    return NextResponse.json(
      {
        error: 'delete proxy failed',
        details: error instanceof Error ? error.message : 'unknown error',
      },
      { status: 502 }
    );
  }
}
