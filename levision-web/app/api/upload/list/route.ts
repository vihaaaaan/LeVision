import { ListObjectsV2Command, S3Client } from '@aws-sdk/client-s3'
import { NextResponse } from 'next/server'

export const runtime = 'nodejs'

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

function fileNameFromKey(key: string) {
  const parts = key.split('/')
  const rawFileName = parts[parts.length - 1] ?? key

  const separatorIndex = rawFileName.indexOf('__')
  if (separatorIndex === -1) return rawFileName

  const decodedName = rawFileName.slice(separatorIndex + 2)
  return decodedName.replace(/-/g, ' ')
}

export async function GET() {
  try {
    const missingEnv = getMissingEnvVars()
    if (missingEnv.length > 0) {
      return NextResponse.json(
        { error: `Missing required environment variables: ${missingEnv.join(', ')}` },
        { status: 500 }
      )
    }

    const publicBaseUrl = process.env.R2_PUBLIC_BASE_URL?.replace(/\/$/, '')
    if (!publicBaseUrl) {
      return NextResponse.json(
        { error: 'Missing required environment variable: R2_PUBLIC_BASE_URL' },
        { status: 500 }
      )
    }

    const result = await createR2Client().send(
      new ListObjectsV2Command({
        Bucket: process.env.R2_BUCKET,
        Prefix: 'uploads/',
        MaxKeys: 100,
      })
    )

    const uploads = (result.Contents ?? [])
      .filter((item): item is NonNullable<typeof item> => !!item.Key)
      .map((item) => ({
        key: item.Key as string,
        name: fileNameFromKey(item.Key as string),
        size: item.Size ?? 0,
        lastModified: item.LastModified?.toISOString() ?? null,
        url: `${publicBaseUrl}/${item.Key as string}`,
      }))
      .sort((a, b) => {
        const aTime = a.lastModified ? Date.parse(a.lastModified) : 0
        const bTime = b.lastModified ? Date.parse(b.lastModified) : 0
        return bTime - aTime
      })

    return NextResponse.json({ uploads })
  } catch (error) {
    console.error('Upload list route failed', error)
    return NextResponse.json(
      { error: 'Unable to list uploaded files right now.' },
      { status: 500 }
    )
  }
}
