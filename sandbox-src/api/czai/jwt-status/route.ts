import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import os from 'os';

export async function GET() {
  try {
    const credsPath = path.join(os.homedir(), '.czai', 'credentials.json');
    if (!fs.existsSync(credsPath)) {
      return NextResponse.json({ needs_jwt: true, email: '' });
    }
    const creds = JSON.parse(fs.readFileSync(credsPath, 'utf-8'));
    return NextResponse.json({
      needs_jwt: !creds.token,
      email: creds.email || '',
    });
  } catch {
    return NextResponse.json({ needs_jwt: true, email: '' });
  }
}
