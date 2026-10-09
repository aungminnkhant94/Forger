import { NextResponse } from 'next/server';

export const runtime = 'nodejs';

/**
 * Remote edit unlock is disabled on public Forger.
 * Mutating bookmarks from a deployed dashboard is intentionally unsupported.
 */
export async function POST() {
  return NextResponse.json(
    {
      error: 'Remote edit is disabled on public Forger',
      detail: 'Use the local CLI (forge) to change bookmarks. Edit/delete API routes are not available.',
    },
    { status: 403 }
  );
}

export async function DELETE() {
  return NextResponse.json(
    {
      error: 'Remote edit is disabled on public Forger',
    },
    { status: 403 }
  );
}
