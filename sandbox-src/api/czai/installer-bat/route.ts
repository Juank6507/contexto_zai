import { PS1_SCRIPT, generateBat } from '@/lib/czai/installer';

export async function GET() {
  const bat = generateBat(PS1_SCRIPT);

  return new Response(bat, {
    status: 200,
    headers: {
      'Content-Type': 'application/octet-stream; charset=utf-8',
      'Content-Disposition': 'attachment; filename="czai-installer.bat"',
      'Content-Length': Buffer.byteLength(bat, 'utf-8').toString(),
    },
  });
}
