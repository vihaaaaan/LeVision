import { randomUUID } from 'node:crypto'
import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3'
import { NextResponse } from 'next/server'
import { createClient } from '@/lib/supabase/server'

export const runtime = 'nodejs'

const MAX_UPLOAD_SIZE_BYTES = 300 * 1024 * 1024
const FILE_TOO_LARGE_MESSAGE = 'File too big (max 300MB).'

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

function getContentLength(request: Request) {
  const header = request.headers.get('content-length')
  if (!header) return null
  const parsed = Number.parseInt(header, 10)
  return Number.isFinite(parsed) ? parsed : null
}

function isFormDataParseFailure(error: unknown) {
  return error instanceof TypeError && /Failed to parse body as FormData/i.test(error.message)
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

    let formData: FormData
    try {
      formData = await request.formData()
    } catch (error) {
      const contentLength = getContentLength(request)
      if (
        isFormDataParseFailure(error) ||
        (contentLength !== null && contentLength > MAX_UPLOAD_SIZE_BYTES)
      ) {
        return NextResponse.json({ error: FILE_TOO_LARGE_MESSAGE }, { status: 413 })
      }
      throw error
    }

    const fileEntry = formData.get('file')
    if (!(fileEntry instanceof File)) {
      return NextResponse.json({ error: 'A file field is required.' }, { status: 400 })
    }

    if (fileEntry.size > MAX_UPLOAD_SIZE_BYTES) {
      return NextResponse.json({ error: FILE_TOO_LARGE_MESSAGE }, { status: 413 })
    }

    if (!fileEntry.type.startsWith('video/')) {
      return NextResponse.json({ error: 'Only video files are allowed.' }, { status: 400 })
    }

    const clipId = randomUUID()
    const ext = sanitizeExt(fileEntry.name)
    const key = `footage/${user.id}/${clipId}.${ext}`
    const body = Buffer.from(await fileEntry.arrayBuffer())

    await createR2Client().send(
      new PutObjectCommand({
        Bucket: process.env.R2_BUCKET,
        Key: key,
        Body: body,
        ContentType: fileEntry.type || 'application/octet-stream',
      })
    )

    const publicBaseUrl = process.env.R2_PUBLIC_BASE_URL?.replace(/\/$/, '')
    const url = publicBaseUrl ? `${publicBaseUrl}/${key}` : null

    const { error: dbError } = await supabase.from('footage').insert({
      id: clipId,
      r2_key: key,
      r2_url: url,
      filename: fileEntry.name,
      uploaded_by: user.id,
      file_size: fileEntry.size,
      vision_status: 'awaiting_game',
    })

    if (dbError) {
      console.error('footage insert failed', dbError)
      return NextResponse.json({ error: 'Upload saved but metadata write failed.' }, { status: 500 })
    }

    return NextResponse.json({ key, url, clipId })
  } catch (error) {
    console.error('Upload route failed', error)
    return NextResponse.json({ error: 'Unable to upload file right now.' }, { status: 500 })
  }
}
