'use client'

import { useRef, useState } from 'react'
import { useAuthStore } from '@/store/auth'
import { authApi } from '@/lib/api'
import toast from 'react-hot-toast'
import { User, Lock, Save, Eye, EyeOff, Camera, Mail, LogOut, Trash2, AlertTriangle, CheckCircle, X } from 'lucide-react'

const INPUT_CLS =
  'w-full px-3.5 py-2.5 rounded-lg bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-sm text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 transition-colors'

// ─── Email Change Modal ───────────────────────────────────────────────────────
function EmailChangeModal({ onClose, currentEmail }: { onClose: () => void; currentEmail: string }) {
  const [step, setStep] = useState<'form' | 'otp'>('form')
  const [newEmail, setNewEmail] = useState('')
  const [password, setPassword] = useState('')
  const [otp, setOtp] = useState('')
  const [loading, setLoading] = useState(false)
  const { user, setUser, tenantId } = useAuthStore()

  async function handleRequest(e: React.FormEvent) {
    e.preventDefault()
    if (!newEmail.trim() || !password) { toast.error('All fields are required'); return }
    setLoading(true)
    try {
      await authApi.requestEmailChange({ new_email: newEmail.trim(), password })
      toast.success('Verification code sent to new email')
      setStep('otp')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to request email change')
    } finally {
      setLoading(false)
    }
  }

  async function handleVerify(e: React.FormEvent) {
    e.preventDefault()
    if (!otp.trim()) { toast.error('Code is required'); return }
    setLoading(true)
    try {
      const res = await authApi.verifyEmailChange({ otp: otp.trim() })
      if (user && tenantId) setUser({ ...user, email: res.data.email }, tenantId)
      toast.success('Email updated successfully')
      onClose()
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Invalid verification code')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-white dark:bg-gray-900 rounded-2xl p-6 w-full max-w-md shadow-2xl border border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between mb-5">
          <h3 className="font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <Mail size={16} className="text-violet-500" /> Change Email
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors"><X size={18} /></button>
        </div>

        {step === 'form' ? (
          <form onSubmit={handleRequest} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Current Email</label>
              <input value={currentEmail} readOnly className={`${INPUT_CLS} opacity-60 cursor-not-allowed`} />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">New Email</label>
              <input type="email" value={newEmail} onChange={e => setNewEmail(e.target.value)} className={INPUT_CLS} placeholder="new@email.com" required />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Confirm with Password</label>
              <input type="password" value={password} onChange={e => setPassword(e.target.value)} className={INPUT_CLS} placeholder="••••••••" required />
            </div>
            <button type="submit" disabled={loading} className="w-full py-2.5 bg-violet-600 hover:bg-violet-700 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50 flex items-center justify-center gap-2">
              {loading ? <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> : <Mail size={14} />}
              Send Verification Code
            </button>
          </form>
        ) : (
          <form onSubmit={handleVerify} className="space-y-4">
            <p className="text-sm text-gray-500 dark:text-gray-400">We sent a 6-digit code to <span className="font-medium text-gray-900 dark:text-white">{newEmail}</span>. Enter it below to confirm.</p>
            <input
              value={otp} onChange={e => setOtp(e.target.value)} className={`${INPUT_CLS} text-center text-2xl tracking-[0.5em] font-mono`}
              placeholder="000000" maxLength={6} required autoFocus
            />
            <button type="submit" disabled={loading} className="w-full py-2.5 bg-violet-600 hover:bg-violet-700 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50 flex items-center justify-center gap-2">
              {loading ? <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> : <CheckCircle size={14} />}
              Verify & Update Email
            </button>
          </form>
        )}
      </div>
    </div>
  )
}

// ─── Delete Account Modal ─────────────────────────────────────────────────────
function DeleteAccountModal({ onClose }: { onClose: () => void }) {
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const { logout } = useAuthStore()

  async function handleDelete(e: React.FormEvent) {
    e.preventDefault()
    if (confirm !== 'DELETE') { toast.error('Type DELETE to confirm'); return }
    setLoading(true)
    try {
      await authApi.deleteMe()
      toast.success('Account deleted')
      logout()
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to delete account')
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-white dark:bg-gray-900 rounded-2xl p-6 w-full max-w-md shadow-2xl border border-red-200 dark:border-red-900/50">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center flex-shrink-0">
            <AlertTriangle size={20} className="text-red-600 dark:text-red-400" />
          </div>
          <div>
            <h3 className="font-semibold text-gray-900 dark:text-white">Delete Account</h3>
            <p className="text-xs text-gray-500">This action cannot be undone</p>
          </div>
          <button onClick={onClose} className="ml-auto text-gray-400 hover:text-gray-600 transition-colors"><X size={18} /></button>
        </div>
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
          Your account and all associated data will be permanently deactivated. Type <span className="font-mono font-bold text-red-600">DELETE</span> to confirm.
        </p>
        <form onSubmit={handleDelete} className="space-y-4">
          <input value={confirm} onChange={e => setConfirm(e.target.value)} className={`${INPUT_CLS} border-red-300 dark:border-red-700 focus:ring-red-500/30 focus:border-red-400`} placeholder="DELETE" />
          <div className="flex gap-3">
            <button type="button" onClick={onClose} className="flex-1 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
              Cancel
            </button>
            <button
              type="submit" disabled={loading || confirm !== 'DELETE'}
              className="flex-1 py-2.5 bg-red-600 hover:bg-red-700 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {loading ? <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> : <Trash2 size={14} />}
              Delete My Account
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ─── Main Profile Page ────────────────────────────────────────────────────────
export default function ProfilePage() {
  const { user, setUser, tenantId } = useAuthStore()

  // Profile form
  const [fullName, setFullName] = useState(user?.full_name || '')
  const [savingProfile, setSavingProfile] = useState(false)

  // Avatar
  const avatarInputRef = useRef<HTMLInputElement>(null)
  const [avatarPreview, setAvatarPreview] = useState<string | null>(user?.avatar_url || null)
  const [uploadingAvatar, setUploadingAvatar] = useState(false)

  // Password form
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showCurrent, setShowCurrent] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [savingPassword, setSavingPassword] = useState(false)

  // Modals
  const [showEmailChange, setShowEmailChange] = useState(false)
  const [showDeleteAccount, setShowDeleteAccount] = useState(false)
  const [loggingOutOthers, setLoggingOutOthers] = useState(false)

  async function handleSaveProfile(e: React.FormEvent) {
    e.preventDefault()
    if (!fullName.trim()) { toast.error('Name cannot be empty'); return }
    setSavingProfile(true)
    try {
      await authApi.updateMe({ full_name: fullName.trim() })
      if (user && tenantId) setUser({ ...user, full_name: fullName.trim() }, tenantId)
      toast.success('Profile updated')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to update profile')
    } finally {
      setSavingProfile(false)
    }
  }

  async function handleAvatarChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    if (!file.type.startsWith('image/')) { toast.error('Only image files are allowed'); return }
    if (file.size > 2 * 1024 * 1024) { toast.error('Image must be less than 2MB'); return }

    const preview = URL.createObjectURL(file)
    setAvatarPreview(preview)

    setUploadingAvatar(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await authApi.uploadAvatar(formData)
      if (user && tenantId) setUser({ ...user, avatar_url: res.data.avatar_url }, tenantId)
      toast.success('Avatar updated')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to upload avatar')
      setAvatarPreview(user?.avatar_url || null)
    } finally {
      setUploadingAvatar(false)
    }
  }

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault()
    if (newPassword.length < 8) { toast.error('Password must be at least 8 characters'); return }
    if (newPassword !== confirmPassword) { toast.error('Passwords do not match'); return }
    setSavingPassword(true)
    try {
      await authApi.changePassword({ current_password: currentPassword, new_password: newPassword })
      toast.success('Password changed — other sessions have been logged out')
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to change password')
    } finally {
      setSavingPassword(false)
    }
  }

  async function handleLogoutOthers() {
    setLoggingOutOthers(true)
    try {
      await authApi.logoutOthers()
      toast.success('All other sessions have been logged out')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to logout other sessions')
    } finally {
      setLoggingOutOthers(false)
    }
  }

  const initials = (user?.full_name || user?.email || '?').charAt(0).toUpperCase()

  return (
    <>
      {showEmailChange && <EmailChangeModal currentEmail={user?.email || ''} onClose={() => setShowEmailChange(false)} />}
      {showDeleteAccount && <DeleteAccountModal onClose={() => setShowDeleteAccount(false)} />}

      <div className="p-8 max-w-2xl mx-auto space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Profile</h1>
          <p className="text-sm text-gray-500 mt-0.5">Manage your account details and security</p>
        </div>

        {/* Avatar + Identity */}
        <div className="flex items-center gap-5 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
          <div className="relative flex-shrink-0">
            {avatarPreview ? (
              <img src={avatarPreview} alt="Avatar" className="w-16 h-16 rounded-full object-cover border-2 border-violet-200 dark:border-violet-800" />
            ) : (
              <div className="w-16 h-16 rounded-full bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center text-white text-2xl font-bold">
                {initials}
              </div>
            )}
            <button
              onClick={() => avatarInputRef.current?.click()}
              disabled={uploadingAvatar}
              title="Upload photo"
              className="absolute -bottom-1 -right-1 w-7 h-7 rounded-full bg-violet-600 hover:bg-violet-700 border-2 border-white dark:border-gray-900 flex items-center justify-center transition-colors disabled:opacity-60"
            >
              {uploadingAvatar
                ? <div className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                : <Camera size={12} className="text-white" />
              }
            </button>
            <input ref={avatarInputRef} type="file" accept="image/*" className="hidden" onChange={handleAvatarChange} />
          </div>
          <div className="min-w-0">
            <p className="font-semibold text-gray-900 dark:text-white truncate">{user?.full_name || '—'}</p>
            <p className="text-sm text-gray-500 truncate">{user?.email}</p>
            <span className="inline-block mt-1 text-xs font-medium px-2 py-0.5 rounded-full bg-violet-50 dark:bg-violet-900/20 text-violet-700 dark:text-violet-300 capitalize">
              {user?.role?.replace('_', ' ')}
            </span>
          </div>
        </div>

        {/* Profile Details */}
        <form onSubmit={handleSaveProfile} className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5 space-y-4">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <User size={15} className="text-violet-500" /> Account Details
          </h2>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Full Name</label>
            <input value={fullName} onChange={e => setFullName(e.target.value)} className={INPUT_CLS} placeholder="Your full name" />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Email</label>
            <div className="flex gap-2">
              <input value={user?.email || ''} readOnly className={`${INPUT_CLS} opacity-60 cursor-not-allowed flex-1`} />
              <button
                type="button"
                onClick={() => setShowEmailChange(true)}
                className="px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 text-xs font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors whitespace-nowrap flex items-center gap-1.5"
              >
                <Mail size={13} /> Change
              </button>
            </div>
          </div>
          <div className="pt-2">
            <button
              type="submit" disabled={savingProfile || !fullName.trim()}
              className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
            >
              {savingProfile ? <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> : <Save size={14} />}
              Save Changes
            </button>
          </div>
        </form>

        {/* Change Password */}
        <form onSubmit={handleChangePassword} className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5 space-y-4">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <Lock size={15} className="text-violet-500" /> Change Password
          </h2>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Current Password</label>
            <div className="relative">
              <input type={showCurrent ? 'text' : 'password'} value={currentPassword} onChange={e => setCurrentPassword(e.target.value)} className={`${INPUT_CLS} pr-10`} placeholder="••••••••" required />
              <button type="button" onClick={() => setShowCurrent(!showCurrent)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors">
                {showCurrent ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">New Password</label>
            <div className="relative">
              <input type={showNew ? 'text' : 'password'} value={newPassword} onChange={e => setNewPassword(e.target.value)} className={`${INPUT_CLS} pr-10`} placeholder="••••••••" required minLength={8} />
              <button type="button" onClick={() => setShowNew(!showNew)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors">
                {showNew ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
            {newPassword && newPassword.length < 8 && <p className="text-xs text-red-500">Must be at least 8 characters</p>}
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">Confirm New Password</label>
            <input type="password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} className={INPUT_CLS} placeholder="••••••••" required />
            {confirmPassword && newPassword !== confirmPassword && <p className="text-xs text-red-500">Passwords do not match</p>}
          </div>
          <p className="text-xs text-gray-400 dark:text-gray-500">⚠️ Changing your password will log out all other active sessions.</p>
          <div className="pt-2">
            <button
              type="submit" disabled={savingPassword || !currentPassword || !newPassword || !confirmPassword}
              className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
            >
              {savingPassword ? <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> : <Lock size={14} />}
              Update Password
            </button>
          </div>
        </form>

        {/* Session Security */}
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5 space-y-4">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <LogOut size={15} className="text-violet-500" /> Session Security
          </h2>
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-gray-800 dark:text-gray-200">Logout Other Devices</p>
              <p className="text-xs text-gray-500 mt-0.5">Revoke access for all browsers and devices except this one.</p>
            </div>
            <button
              onClick={handleLogoutOthers} disabled={loggingOutOthers}
              className="flex-shrink-0 flex items-center gap-2 px-3 py-2 border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
            >
              {loggingOutOthers ? <div className="w-4 h-4 border-2 border-gray-400/30 border-t-gray-600 rounded-full animate-spin" /> : <LogOut size={14} />}
              Logout Others
            </button>
          </div>
        </div>

        {/* Danger Zone */}
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-red-200 dark:border-red-900/50 p-5 space-y-4">
          <h2 className="text-sm font-semibold text-red-600 dark:text-red-400 flex items-center gap-2">
            <AlertTriangle size={15} /> Danger Zone
          </h2>
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-gray-800 dark:text-gray-200">Delete Account</p>
              <p className="text-xs text-gray-500 mt-0.5">Permanently deactivate your account and all associated data. This cannot be undone.</p>
            </div>
            <button
              onClick={() => setShowDeleteAccount(true)}
              className="flex-shrink-0 flex items-center gap-2 px-3 py-2 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg text-sm font-medium transition-colors"
            >
              <Trash2 size={14} /> Delete
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
