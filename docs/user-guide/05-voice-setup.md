# Voice Setup

Let customers call your AI agent directly by phone. This guide walks you through setting up voice capabilities using Twilio.

---

## What Is Voice?

Voice lets your customers call your business and talk to your AI agent just like they would chat with it on your website. Your agent can:

- Answer questions over the phone
- Book appointments
- Take orders
- Collect payments
- Transfer calls to a human when needed
- Send follow-up texts or emails after the call

### Voice vs. Chat: What's Different?

| Chat | Voice |
|------|-------|
| Customers type messages | Customers speak |
| Agent responds with text | Agent responds with speech |
| Works on your website | Works on any phone |
| Good for detailed questions | Good for quick interactions |
| Customers can multitask | Customers give full attention |

Your agent uses the same knowledge base, playbooks, and tools for both chat and voice. The only difference is how customers interact.

---

## Setting Up Twilio

Twilio is the service that handles phone calls for your agent. It's a trusted company used by thousands of businesses worldwide.

### Step 1: Create a Twilio Account

1. Go to **twilio.com** and click **"Sign Up"**
2. Enter your name, email, and password
3. Verify your email address
4. Verify your personal phone number (Twilio requires this for security)

> **Note:** Twilio offers a free trial that includes a phone number and some free credits. This is enough to test voice calls before committing.

### Step 2: Get a Phone Number

1. After signing up, go to your Twilio **Console** (dashboard)
2. Click **"Get a Phone Number"** or go to **Phone Numbers > Manage > Buy a Number**
3. Choose a phone number:
   - Search by area code to get a local number
   - Or choose a toll-free number (starts with 800, 888, 877, etc.)
4. Click **"Buy"** (free during trial)

**Tip:** Choose a number that's easy to remember or matches your existing business number pattern.

### Step 3: Find Your Credentials

You'll need three pieces of information from Twilio to connect it to AscenAI2:

1. **Account SID** - This identifies your Twilio account
2. **Auth Token** - This proves you own the account (keep this secret!)
3. **Phone Number** - The number you just purchased

**Where to find them:**
1. Log in to your Twilio account
2. Go to the **Console Dashboard** (the main page after logging in)
3. You'll see your **Account SID** and **Auth Token** near the top of the page
4. Your **Phone Number** is listed under **Phone Numbers > Active Numbers**

---

## Connecting Twilio to AscenAI2

### Step 1: Go to Voice Settings

1. In your AscenAI2 dashboard, click **"Agents"** in the left sidebar
2. Click on the agent you want to set up for voice
3. Click the **"Voice"** tab in the agent settings

### Step 2: Enter Twilio Credentials

1. Click **"Connect Twilio"**
2. Enter your **Account SID** (copied from Twilio)
3. Enter your **Auth Token** (copied from Twilio)
4. Enter your **Twilio Phone Number** (the number you purchased)
5. Click **"Connect"**

### Step 3: Configure Voice Settings

After connecting, you'll see voice configuration options:

**Voice Greeting**
- This is what customers hear when they call
- Example: "Thank you for calling Smile Bright Dental. How can I help you today?"
- Keep it short and clear (under 15 seconds)

**Language**
- Choose the language your agent will speak
- Must match the language you set for your agent

**Voice**
- Choose from available voices
- Preview each voice before selecting
- Pick one that matches your brand (professional, friendly, casual)

**Speech Speed**
- **Slow** - Good for older customers or complex information
- **Normal** - Default, works for most situations
- **Fast** - Good for quick confirmations

**Background Music**
- Optional: Play soft music while customers are on hold
- Choose from available tracks or upload your own

### Step 4: Save and Test

1. Click **"Save Settings"**
2. Call your Twilio phone number from your cell phone
3. Talk to your agent just like you would in the chat preview
4. Test common scenarios (booking, FAQs, payments)

---

## Testing Voice Calls

### What to Test

**Basic Conversation:**
- Call and ask about your business hours
- Ask about your services
- Ask a question covered in your knowledge base

**Playbook Scenarios:**
- Try to book an appointment
- Ask about pricing
- Leave feedback

**Tool Actions:**
- Book a test appointment and check your calendar
- Ask the agent to send you an email and check that it arrives
- If payments are set up, do a small test transaction

**Edge Cases:**
- Speak quickly to test speech recognition
- Use background noise (TV, music) to test in real-world conditions
- Ask a question your agent doesn't know the answer to
- Try to transfer to a human (if you have this set up)

### Testing Tips

- **Speak clearly** - Test how well the agent understands normal speech
- **Use different accents** - If your customers have diverse accents, test with them
- **Test during busy hours** - Call during your business's peak hours to simulate real conditions
- **Test from different phones** - Cell phones, landlines, VoIP phones may sound different

---

## Voice Call Flow

Here's what happens when a customer calls your agent:

1. **Customer dials your Twilio number**
2. **Agent answers with your voice greeting** - "Thank you for calling [Business]. How can I help you?"
3. **Customer speaks their request** - "I'd like to book an appointment."
4. **Agent processes the request** - Uses playbooks and tools to handle the conversation
5. **Agent responds with speech** - "I'd be happy to help! What day works best for you?"
6. **Conversation continues** until the customer's need is met
7. **Agent performs actions** - Books appointment, sends confirmation, etc.
8. **Call ends** - "Thank you for calling! Have a great day."

---

## Advanced Voice Features

### Call Transfer

Set up your agent to transfer calls to a human when needed.

**When to transfer:**
- Customer asks for a specific person
- Customer is upset and wants to speak to a manager
- Customer's request is outside the agent's capabilities
- Customer explicitly asks to speak to a human

**How to set up:**
1. In your agent's voice settings, go to **"Call Transfer"**
2. Enter the phone number to transfer to
3. Set the transfer message: "Let me connect you with someone who can help. Please hold."
4. Choose when to transfer (specific triggers, customer request, negative sentiment)

### Voicemail Detection

If a customer calls and no one answers (for transfers), you can set up voicemail.

**How to set up:**
1. In your voice settings, go to **"Voicemail"**
2. Record or type your voicemail greeting
3. Choose what happens when voicemail is detected (leave a message, send a text, etc.)

### Call Recording

Record calls for quality assurance and training.

**How to set up:**
1. In your voice settings, go to **"Call Recording"**
2. Toggle **"Record Calls"** to on
3. Choose whether to announce recording ("This call may be recorded for quality assurance")
4. Recordings are stored in your dashboard under **Voice > Call History**

> **Important:** Check your local laws about call recording. Some regions require all parties to consent.

### After-Hours Handling

Set up different behavior for when your business is closed.

**How to set up:**
1. In your voice settings, go to **"After Hours"**
2. Set your business hours
3. Choose the after-hours message: "Thank you for calling. Our office is currently closed. Our hours are [hours]. Please leave a message and we'll get back to you."
4. Choose what happens (take a message, send a text with hours, etc.)

---

## Voice Best Practices

### 1. Keep Responses Short

People on the phone have shorter attention spans than people reading chat. Keep responses under 2-3 sentences.

**Good:** "We're open Monday to Friday, 9 to 5. Would you like to book an appointment?"
**Bad:** "Our business hours are as follows: Monday through Friday, we are open from 9:00 AM to 5:00 PM. On Saturdays, we are open from 9:00 AM to 1:00 PM. We are closed on Sundays and all major holidays. Would you like to know anything else?"

### 2. Use a Clear Voice Greeting

Your greeting sets the tone for the entire call.

**Good examples:**
- "Thank you for calling Smile Bright Dental. How can I help you today?"
- "Hi, you've reached Tony's Pizza. What can I get started for you?"
- "Welcome to Serenity Salon. I'm here to help you book your next appointment."

### 3. Confirm Important Information

When collecting information over the phone, repeat it back to confirm.

**Example:**
Customer: "My appointment is for Tuesday at 3."
Agent: "Great, I have you down for Tuesday at 3 PM. Is that correct?"

### 4. Offer to Follow Up by Text or Email

After a voice call, offer to send a summary.

**Example:**
"Would you like me to text you a confirmation of your appointment?"

### 5. Handle Background Noise Gracefully

If the agent can't understand the customer:
- "I'm sorry, I didn't catch that. Could you please repeat it?"
- After 2-3 failed attempts: "Let me connect you with someone who can help."

---

## Troubleshooting Voice Issues

### Call Not Connecting
- Verify your Twilio account is active and has credits
- Check that your Twilio phone number is still active
- Verify your Account SID and Auth Token are correct in AscenAI2

### Agent Not Understanding Speech
- Check that the language setting matches what customers are speaking
- Test with different voices (some handle accents better)
- Adjust speech speed to slow if customers are having trouble

### Poor Audio Quality
- Check your Twilio phone number type (local numbers typically have better quality)
- Test from different phones to isolate the issue
- Check your internet connection if using VoIP

### Calls Dropping
- Check your Twilio account for any service alerts
- Verify your AscenAI2 agent is running and not paused
- Check call logs in both Twilio and AscenAI2 for error messages

### High Costs
- Review your Twilio usage dashboard
- Check call durations (long calls cost more)
- Set up call duration limits if needed
- Consider using chat for complex conversations that take longer

---

## Voice Pricing

Voice calls are billed separately from chat. You'll be charged for:

- **Per-minute usage** - Based on the duration of each call
- **Phone number** - Monthly cost for your Twilio phone number
- **Speech processing** - Converting speech to text and text to speech

Your AscenAI2 plan includes a certain number of voice minutes per month. Check your plan details in **Billing > Usage** to see your allowance and current usage.

---

## What's Next?

Now that voice is set up:
- **Playbooks** - Make sure your playbooks work well for voice conversations
- **Tools** - Test that tools (calendar, email, payments) work during voice calls
- **Team** - Share your voice number with your team and train them on how calls are handled
