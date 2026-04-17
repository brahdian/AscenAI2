import asyncio
import os
import uuid
import json
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, init_db
from app.models.user import User
from app.models.tenant import Tenant, TenantUsage
from app.models.platform import PlatformSetting
from app.services.auth_service import auth_service
from app.services.admin_service import DEFAULT_ROLES as ROLES

# billing.py PLANS (copying here for seeding)
PLANS = {
    "starter": {
        "display_name": "Starter",
        "description": "For growing businesses with higher conversation volume.",
        "badge": "Entry Level",
        "color": "border-white/10",
        "highlight": False,
        "price_per_agent": 49.00,
        "chat_equivalents_included": 20_000,
        "base_chat_equivalents": 20_000,
        "voice_minutes_included": 0,
        "playbooks_per_agent": 5,
        "rag_documents": 50,
        "team_seats": 5,
        "overage_per_chat_equivalent": 0.002,
        "overage_per_voice_minute": 0.10,
        "voice_enabled": False,
        "model": "chat_equivalent",
    },
    "growth": {
        "display_name": "Growth",
        "description": "For growing businesses needing voice capability.",
        "badge": "Most Popular",
        "color": "border-violet-500/50",
        "highlight": True,
        "price_per_agent": 99.00,
        "chat_equivalents_included": 80_000,
        "base_chat_equivalents": 20_000,
        "voice_minutes_included": 1500,
        "playbooks_per_agent": 5,
        "rag_documents": 50,
        "team_seats": 5,
        "overage_per_chat_equivalent": 0.002,
        "overage_per_voice_minute": 0.10,
        "voice_enabled": True,
        "model": "chat_equivalent",
    },
    "business": {
        "display_name": "Business",
        "description": "For high-volume businesses with heavy voice usage.",
        "badge": "Power User",
        "color": "border-white/10",
        "highlight": False,
        "price_per_agent": 199.00,
        "chat_equivalents_included": 170_000,
        "base_chat_equivalents": 20_000,
        "voice_minutes_included": 3500,
        "playbooks_per_agent": None,
        "rag_documents": 200,
        "team_seats": 10,
        "overage_per_chat_equivalent": 0.002,
        "overage_per_voice_minute": 0.10,
        "voice_enabled": True,
        "model": "chat_equivalent",
    },
    "enterprise": {
        "display_name": "Enterprise",
        "description": "For high-volume businesses with custom requirements.",
        "badge": "Contact Sales",
        "color": "border-white/10",
        "highlight": False,
        "price_per_agent": None,
        "chat_equivalents_included": None,
        "base_chat_equivalents": None,
        "voice_minutes_included": None,
        "playbooks_per_agent": None,
        "rag_documents": None,
        "team_seats": None,
        "overage_per_chat_equivalent": 0.0,
        "overage_per_voice_minute": 0.0,
        "voice_enabled": True,
        "model": "chat_equivalent",
    },
}

# global_language_config
GLOBAL_LANGUAGE_CONFIG = {
    "languages": [
        {"code": "en", "label": "English (Global)"},
        {"code": "en-CA", "label": "English (Canada)"},
        {"code": "fr", "label": "French (France)"},
        {"code": "fr-CA", "label": "French (Canada / Québec)"},
        {"code": "es", "label": "Spanish"},
        {"code": "es-MX", "label": "Spanish (Mexico)"},
        {"code": "de", "label": "German"},
        {"code": "it", "label": "Italian"},
        {"code": "pt", "label": "Portuguese"},
        {"code": "pt-BR", "label": "Portuguese (Brazil)"},
        {"code": "nl", "label": "Dutch"},
        {"code": "pl", "label": "Polish"},
        {"code": "ru", "label": "Russian"},
        {"code": "zh", "label": "Chinese (Mandarin)"},
        {"code": "ja", "label": "Japanese"},
        {"code": "ko", "label": "Korean"},
        {"code": "hi", "label": "Hindi"},
        {"code": "pa", "label": "Punjabi"},
        {"code": "ar", "label": "Arabic"},
        {"code": "tr", "label": "Turkish"},
        {"code": "uk", "label": "Ukrainian"},
        {"code": "vi", "label": "Vietnamese"},
        {"code": "id", "label": "Indonesian"},
        {"code": "tl", "label": "Tagalog / Filipino"},
    ],
    "greetings": {
        "en": "Thank you for calling.",
        "fr": "Merci de nous avoir contactés.",
        "es": "Gracias por llamar.",
        "de": "Danke für Ihren Anruf.",
        "it": "Grazie per aver chiamato.",
        "pt": "Obrigado por ligar.",
        "ja": "お電話ありがとうございます。",
        "ko": "전화해 주셔서 감사합니다.",
        "zh": "感谢您的致电。",
        "hi": "नमस्ते, कॉल करने के लिए धन्यवाद।",
        "pa": "ਸਤਿ ਸ੍ਰੀ ਅਕਾਲ, ਕਾਲ ਕਰਨ ਲਈ ਧੰਨਵਾਦ।",
        "ar": "شكراً لاتصالك.",
        "tr": "Aradığınız için teşekkür ederiz.",
        "nl": "Bedankt voor uw oproep.",
        "pl": "Dziękujemy za telefon.",
        "ru": "Спасибо за ваш звонок.",
        "vi": "Cảm ơn bạn đã gọi.",
        "uk": "Дякуємо за дзвінок.",
        "id": "Terima kasih telah menelepon.",
        "tl": "Salamat sa pagtawag.",
    },
    "assist_prefixes": {
        "en": "I can assist you in",
        "fr": "Je peux vous aider en",
        "es": "Puedo ayudarle en",
        "de": "Ich kann Sie auf",
        "it": "Posso assistervi in",
        "pt": "Posso ajudá-lo em",
        "ja": "対応可能言語:",
        "ko": "지원 언어:",
        "zh": "我可以提供以下语言的服务:",
        "hi": "मैं आपकी सहायता कर सकता हूँ",
        "pa": "ਮੈਂ ਤੁਹਾਡੀ ਮਦਦ ਕਰ ਸਕਦਾ ਹਾਂ",
        "ar": "يمكنني مساعدتك في",
        "tr": "Size şu dillerde yardımcı olabilirim:",
        "nl": "Ik kan u helpen in het",
        "pl": "Mogę pomóc w języku",
        "ru": "Я могу помочь вам на",
        "vi": "Tôi có thể hỗ trợ bạn bằng tiếng",
        "uk": "Я можу допомогти вам",
        "id": "Saya dapat membantu Anda dalam bahasa",
        "tl": "Maaari kitang tulungan sa wikang",
    },
    "fallbacks": {
        "en": "Sorry, I didn't quite catch that. Could you say that again?",
        "fr": "Désolé, je n'ai pas bien compris. Pourriez-vous répéter?",
        "zh": "对不起，我没听清。请再说一遍。",
        "es": "Lo siento, no he entendido bien. ¿Probablemente repetir?",
        "de": "Entschuldigung, das habe ich nicht verstanden. Könnten Sie das bitte wiederholen?",
        "it": "Scusa, non ho capito bene. Potresti ripetere?",
        "pt": "Desculpe, não entendi bem. Você poderia repetir?",
        "ja": "すみません、聞き取れませんでした。もう一度おっしゃっていただけますか？",
        "ko": "죄송합니다, 잘 못 들었습니다. 다시 말씀해 주시겠어요?",
        "hi": "क्षमा करें, मुझे समझ नहीं आया। क्या आप फिर से कह सकते हैं?",
        "pa": "ਮਾਫ ਕਰਨਾ, ਮੈਨੂੰ ਸਮਝ ਨਹੀਂ ਆਇਆ। ਕੀ ਤੁਸੀਂ ਫਿਰ ਤੋਂ ਕਹਿ ਸਕਦੇ ਹੋ?",
        "ar": "عذراً، لم أفهم ذلك جيداً. هل يمكنك تكرار ذلك؟",
        "tr": "Üzgünüm, tam olarak anlayamadım. Tekrar eder misiniz?",
        "nl": "Sorry, ik heb het niet goed begrepen. Kunt u dat nog eens herhalen?",
        "pl": "Przepraszam, nie zrozumiałem. Czy możesz powtórzyć?",
        "ru": "Извините, я не совсем понял. Не могли бы вы повторить?",
        "vi": "Xin lỗi, tôi không nghe rõ. Bạn có thể nói lại được không?",
        "uk": "Вибачте, я не зовсім зрозумів. Чи могли б ви повторити?",
        "id": "Maaf, saya kurang menangkap maksud Anda. Bisa diulangi?",
        "tl": "Pasensya na, hindi ko nakuha iyon. Maaari mo bang sabihin muli?",
    }
}

async def seed_platform():
    # Initialize DB tables before seeding since this runs before FastAPI startup
    await init_db()
    async with AsyncSessionLocal() as db:
        print("--- Seeding Platform Settings ---")
        
        # 1. Seed RBAC Roles
        rbac_setting_res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "rbac_roles"))
        rbac_setting = rbac_setting_res.scalar_one_or_none()
        if not rbac_setting:
            db.add(PlatformSetting(
                key="rbac_roles",
                value=ROLES,
                description="RBAC Roles and Permission Mappings"
            ))
            print("Seeded 'rbac_roles'")
        else:
            print("'rbac_roles' already exists")

        # 2. Seed Billing Plans
        plans_setting_res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "billing_plans"))
        plans_setting = plans_setting_res.scalar_one_or_none()
        if not plans_setting:
            db.add(PlatformSetting(
                key="billing_plans",
                value=PLANS,
                description="Platform Billing Plans and Pricing"
            ))
            print("Seeded 'billing_plans'")
        else:
            # Update existing plans to include new display fields if missing
            from sqlalchemy.orm.attributes import flag_modified
            current_value = dict(plans_setting.value)
            updated = False
            for key, default_data in PLANS.items():
                if key not in current_value:
                    print(f"Plan '{key}' missing from DB, adding...")
                    current_value[key] = default_data
                    updated = True
                else:
                    if not isinstance(current_value[key], dict):
                        current_value[key] = default_data
                        updated = True
                        continue
                        
                    for field, val in default_data.items():
                        if field not in current_value[key]:
                            print(f"Field '{field}' missing from plan '{key}', adding...")
                            current_value[key][field] = val
                            updated = True
            
            if updated:
                plans_setting.value = current_value
                flag_modified(plans_setting, "value")
                await db.flush()
                print("Updated 'billing_plans' with new fields")
            else:
                print("'billing_plans' is already up to date")

        # 3. Seed Platform Guardrails (initial enabled state — all on)
        gr_setting_res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "platform_guardrails"))
        if not gr_setting_res.scalar_one_or_none():
            db.add(PlatformSetting(
                key="platform_guardrails",
                value={},  # Empty = all defaults apply (all enabled)
                description="Per-guardrail enable/disable overrides. Managed via /admin/guardrails.",
                is_sensitive=False,
                is_public=False,
            ))
            print("Seeded 'platform_guardrails'")
        else:
            print("'platform_guardrails' already exists")

        # 4. Seed System Defaults
        defaults_setting_res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "system_defaults"))
        defaults_setting = defaults_setting_res.scalar_one_or_none()
        if not defaults_setting:
            db.add(PlatformSetting(
                key="system_defaults",
                value={
                    "default_role": "viewer",
                    "default_plan": "starter",
                    "app_name": "AscenAI",
                    "support_email": "support@ascenai.com"
                },
                description="General System Default Settings"
            ))
            print("Seeded 'system_defaults'")
        else:
            print("'system_defaults' already exists")

        # 5. Seed Language Config
        lang_setting_res = await db.execute(select(PlatformSetting).where(PlatformSetting.key == "global_language_config"))
        lang_setting = lang_setting_res.scalar_one_or_none()
        if not lang_setting:
            db.add(PlatformSetting(
                key="global_language_config",
                value=GLOBAL_LANGUAGE_CONFIG,
                description="Global language list and localization strings"
            ))
            print("Seeded 'global_language_config'")
        else:
            from sqlalchemy.orm.attributes import flag_modified
            lang_setting.value = GLOBAL_LANGUAGE_CONFIG
            flag_modified(lang_setting, "value")
            print("Updated 'global_language_config'")

        print("\n--- Seeding Super Admin ---")
        
        email = os.getenv("SUPERADMIN_EMAIL", "admin@ascenai.com")
        password = os.getenv("SUPERADMIN_PASSWORD", "admin123")
        
        # Check for System Tenant
        tenant_res = await db.execute(select(Tenant).where(Tenant.slug == "system"))
        system_tenant = tenant_res.scalar_one_or_none()
        
        if not system_tenant:
            system_tenant = Tenant(
                id=uuid.uuid4(),
                name="System Administration",
                slug="system",
                business_type="platform",
                business_name="AscenAI Platform",
                email=email,
                plan="enterprise",
                plan_limits={},
                is_active=True
            )
            db.add(system_tenant)
            await db.flush()
            
            # Add usage record
            db.add(TenantUsage(tenant_id=system_tenant.id))
            print(f"Created System Tenant: {system_tenant.id}")
        else:
            print(f"System Tenant already exists: {system_tenant.id}")

        # Check for Super Admin User
        user_res = await db.execute(select(User).where(User.email == email.lower()))
        admin_user = user_res.scalar_one_or_none()
        
        if not admin_user:
            admin_user = User(
                id=uuid.uuid4(),
                tenant_id=system_tenant.id,
                email=email.lower(),
                hashed_password=auth_service.hash_password(password),
                full_name="Platform Administrator",
                role="super_admin",
                is_active=True,
                is_email_verified=True
            )
            db.add(admin_user)
            print(f"Created Super Admin User: {email}")
        else:
            # Update password if it changed in env
            admin_user.hashed_password = auth_service.hash_password(password)
            print(f"Updated Super Admin User password: {email}")

        await db.commit()
        print("\nSeeding Complete!")

if __name__ == "__main__":
    asyncio.run(seed_platform())
