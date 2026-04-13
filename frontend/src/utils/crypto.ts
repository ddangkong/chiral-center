/**
 * 간단한 AES-GCM 암호화/복호화 (Web Crypto API)
 * 브라우저 fingerprint 기반 키 생성 — 같은 브라우저에서만 복호화 가능
 */

const SALT = 'chiral-center-2026'

async function deriveKey(): Promise<CryptoKey> {
  // 브라우저 fingerprint로 키 생성 (userAgent + language + screen)
  const fingerprint = [
    navigator.userAgent,
    navigator.language,
    screen.width,
    screen.height,
    SALT,
  ].join('|')

  const encoder = new TextEncoder()
  const keyMaterial = await crypto.subtle.importKey(
    'raw',
    encoder.encode(fingerprint),
    'PBKDF2',
    false,
    ['deriveKey'],
  )

  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt: encoder.encode(SALT), iterations: 100000, hash: 'SHA-256' },
    keyMaterial,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  )
}

export async function encrypt(plaintext: string): Promise<string> {
  try {
    const key = await deriveKey()
    const encoder = new TextEncoder()
    const iv = crypto.getRandomValues(new Uint8Array(12))
    const encrypted = await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv },
      key,
      encoder.encode(plaintext),
    )
    // iv + ciphertext → base64
    const combined = new Uint8Array(iv.length + new Uint8Array(encrypted).length)
    combined.set(iv)
    combined.set(new Uint8Array(encrypted), iv.length)
    return btoa(String.fromCharCode(...combined))
  } catch {
    return plaintext // fallback: 암호화 실패 시 평문
  }
}

export async function decrypt(ciphertext: string): Promise<string> {
  try {
    // 평문인지 확인 (base64가 아니면 이미 평문)
    if (!ciphertext || ciphertext.startsWith('sk-') || ciphertext.startsWith('{')) {
      return ciphertext
    }
    const key = await deriveKey()
    const combined = Uint8Array.from(atob(ciphertext), c => c.charCodeAt(0))
    const iv = combined.slice(0, 12)
    const data = combined.slice(12)
    const decrypted = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv },
      key,
      data,
    )
    return new TextDecoder().decode(decrypted)
  } catch {
    return ciphertext // fallback: 복호화 실패 시 원본 반환
  }
}
