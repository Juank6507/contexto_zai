import { PS1_SCRIPT } from '@/lib/czai/installer';

export async function GET() {
  return new Response(PS1_SCRIPT, {
    status: 200,
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'Content-Disposition': 'attachment; filename="czai-installer.ps1"',
    },
  });
}
