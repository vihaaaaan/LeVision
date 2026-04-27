import { randomUUID } from 'node:crypto'
import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3'
import { getSignedUrl } from '@aws-sdk/s3-request-presigner'
import { NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'

export const runtime = 'nodejs'

const MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024 * 1024
const PRESIGN_EXPIRES_IN = 600 // 10 minutes

const REQUIRED_ENV_VARS = [
  'R2_ACCOUNT_ID',
  'R2_ACCESS_KEY_ID',
  'R2_SECRET_ACCESS_KEY',
  'R2_BUCKET',
] as const

function getMissingEnvVars() {
  return REQUIRED_ENV_VARS.filter((key) => !process.env[key])
}

function createR2Client() {
  return new S3Client({
    region: 'auto',
    endpoint: `https://${process.env.R2_ACCOUNT_ID}.r2.cloudflarestorage.com`,
    credentials: {
      accessKeyId: process.env.R2_ACCESS_KEY_ID as string,
      secretAccessKey: process.env.R2_SECRET_ACCESS_KEY as string,
    },
  })
}

function sanitizeExt(filename: string): string {
  const raw = filename.split('.').pop()?.toLowerCase() ?? 'mp4'
  return raw.replace(/[^a-z0-9]/g, '').slice(0, 10) || 'mp4'
}

type UploadRequestBody = {
  filename: string
  contentType: string
  fileSize: number
}

export async function POST(request: Request) {
  try {
    const missingEnv = getMissingEnvVars()
    if (missingEnv.length > 0) {
      return NextResponse.json(
        { error: `Missing required environment variables: ${missingEnv.join(', ')}` },
        { status: 500 }
      )
    }

    const supabase = await createClient()
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

    const body = (await request.json()) as UploadRequestBody

    if (!body.filename || !body.contentType || !body.fileSize) {
      return NextResponse.json({ error: 'filename, contentType, and fileSize are required' }, { status: 400 })
    }

    if (body.fileSize > MAX_UPLOAD_SIZE_BYTES) {
      return NextResponse.json({ error: 'File too big (max 5GB).' }, { status: 413 })
    }

    if (!body.contentType.startsWith('video/')) {
      return NextResponse.json({ error: 'Only video files are allowed.' }, { status: 400 })
    }

    const clipId = randomUUID()
    const ext = sanitizeExt(body.filename)
    const key = `footage/${user.id}/${clipId}.${ext}`

    const r2 = createR2Client()
    const presignedUrl = await getSignedUrl(
      r2,
      new PutObjectCommand({
        Bucket: process.env.R2_BUCKET,
        Key: key,
        ContentType: body.contentType,
        ContentLength: body.fileSize,
      }),
      { expiresIn: PRESIGN_EXPIRES_IN }
    )

    const publicBaseUrl = process.env.R2_PUBLIC_BASE_URL?.replace(/\/$/, '')
    const url = publicBaseUrl ? `${publicBaseUrl}/${key}` : null

    const { error: dbError } = await supabase.from('footage').insert({
      id: clipId,
      r2_key: key,
      r2_url: url,
      filename: body.filename,
      uploaded_by: user.id,
      file_size: body.fileSize,
      vision_status: 'awaiting_game',
    })

    if (dbError) {
      console.error('footage insert failed', dbError)
      return NextResponse.json({ error: 'Failed to create footage record.' }, { status: 500 })
    }

    return NextResponse.json({ presignedUrl, key, url, clipId })
  } catch (error) {
    console.error('Upload route failed', error)
    return NextResponse.json({ error: 'Unable to upload file right now.' }, { status: 500 })
  }
}
