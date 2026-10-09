import { NextResponse } from 'next/server';

export const runtime = 'nodejs';

/**
 * Remote bookmark delete is disabled on public Forger.
 * No NEXT_PUBLIC secrets, no upstream delete proxy.
 */
export async function DELETE() {
  return NextResponse.json(
    {
      error: 'Remote delete is disabled on public Forger',
      detail: 'Use the local CLI to remove bookmarks. This dashboard is read-only.',
    },
    { status: 403 }
  );
}
