# Tools & Integrations

Give your AI agent the ability to take real actions. Tools are the capabilities that let your agent do things like send emails, book appointments, and collect payments.

---

## What Are Tools?

Think of tools as your agent's superpowers. Without tools, your agent can only chat and answer questions. With tools, your agent can:

- Send confirmation emails
- Book appointments on your calendar
- Send text message reminders
- Collect payments
- Update your customer database
- Notify your team about new leads

### Tools vs. Playbooks

| Playbooks | Tools |
|-----------|-------|
| Conversation scripts | Real-world actions |
| Tell the agent what to say | Tell the agent what to do |
| Example: "I'll book that for you!" | Example: Actually adds the event to your calendar |

Playbooks and tools work together. A playbook guides the conversation, and tools perform the actions during or after that conversation.

**Example:** A booking playbook tells your agent to ask for the customer's preferred date and time. The calendar tool actually creates the event in your Google Calendar.

---

## Available Tools

### SMS Notifications

Send text messages to customers automatically.

**Use cases:**
- Appointment reminders
- Order confirmations
- Follow-up messages
- Promotional offers

**How to configure:**
1. Go to **Tools** in the left sidebar
2. Click **"SMS Notifications"**
3. Enter your phone number (this is the number messages will appear to come from)
4. Click **"Connect"**
5. Verify your phone number by entering the code sent to you

**Example - Appointment Reminder:**
When a customer books an appointment, your agent automatically sends: "Hi [Name], this is a reminder about your appointment at [Business] tomorrow at [Time]. Reply CANCEL to reschedule."

---

### Email Sending

Send emails to customers or your team.

**Use cases:**
- Booking confirmations
- Receipts and invoices
- Welcome emails for new customers
- Internal notifications to your team

**How to configure:**
1. Go to **Tools** in the left sidebar
2. Click **"Email"**
3. Connect your email provider (Gmail, Outlook, or custom SMTP)
4. Authorize AscenAI2 to send emails on your behalf
5. Set up email templates or use the default ones

**Example - Booking Confirmation Email:**
```
Subject: Your Appointment is Confirmed - [Business Name]

Hi [Customer Name],

Your appointment has been confirmed!

Date: [Date]
Time: [Time]
Service: [Service]
Location: [Address]

We look forward to seeing you!

[Business Name]
[Phone Number]
```

---

### Calendar Booking

Connect your calendar so your agent can check availability and book appointments.

**Supported calendars:**
- Google Calendar
- Microsoft Outlook Calendar
- Apple Calendar (via CalDAV)

**How to configure:**
1. Go to **Tools** in the left sidebar
2. Click **"Calendar"**
3. Choose your calendar provider
4. Sign in and authorize AscenAI2 to access your calendar
5. Select which calendar to use (if you have multiple)
6. Set your working hours and buffer times between appointments

**Settings you can customize:**
- **Working hours** - When appointments can be booked
- **Buffer time** - Gap between appointments (e.g., 15 minutes)
- **Advance notice** - How far in advance customers can book (e.g., same-day, 24 hours, 1 week)
- **Maximum bookings per day** - Limit how many appointments can be booked

**Example - Dental Clinic:**
- Working hours: Monday-Friday 9 AM - 5 PM, Saturday 9 AM - 1 PM
- Buffer time: 15 minutes between appointments
- Advance notice: Same-day bookings allowed
- Maximum bookings: 20 per day

**Example - Hair Salon:**
- Working hours: Tuesday-Saturday 10 AM - 7 PM
- Buffer time: 30 minutes between appointments
- Advance notice: 24 hours minimum
- Maximum bookings: 12 per day

---

### Payment Collection

Let your agent collect payments directly in the conversation.

**Supported payment providers:**
- **Stripe** - Credit and debit card payments
- **Square** - In-person and online payments
- **PayPal** - PayPal account and card payments
- **Twilio Pay** - Phone-based payments (for voice calls)

#### Setting Up Stripe

1. Go to **Tools** > **Payments**
2. Click **"Connect Stripe"**
3. You'll be redirected to Stripe's website
4. Sign in to your Stripe account (or create one)
5. Authorize the connection
6. You'll be redirected back to AscenAI2

**What you need:**
- A Stripe account (free to create at stripe.com)
- Your business bank account linked to Stripe
- Stripe processes payments and deposits them into your bank account (usually within 2 business days)

#### Setting Up Square

1. Go to **Tools** > **Payments**
2. Click **"Connect Square"**
3. Sign in to your Square account
4. Authorize the connection

#### Setting Up PayPal

1. Go to **Tools** > **Payments**
2. Click **"Connect PayPal"**
3. Sign in to your PayPal Business account
4. Authorize the connection

#### Setting Up Twilio Pay (Voice Payments)

1. Go to **Tools** > **Payments**
2. Click **"Connect Twilio Pay"**
3. Enter your Twilio Account SID and Auth Token
4. Configure your payment phone number

**Use cases for payment collection:**
- Collect deposits for appointments
- Process orders over chat
- Collect overdue invoices
- Accept payments for services

**Example - Pizza Shop:**
Customer: "I'd like to order a large pepperoni pizza."
Agent: "Great choice! That'll be $18.99 including tax. Would you like to pay now with your credit card?"
Customer: "Yes."
Agent: "Perfect! I'll send you a secure payment link. Once payment is confirmed, your order will be prepared right away."

---

### Webhook Calls

Webhooks let your agent send information to other apps and services you use.

**What is a webhook?**
A webhook is like a messenger that delivers information from your agent to another app. When something happens in a conversation, the webhook sends that information to the app you choose.

**Use cases:**
- Send new leads to your CRM (Customer Relationship Management) system
- Update your customer database
- Create support tickets
- Add customers to your email marketing list
- Notify your team on Slack or Microsoft Teams

**How to configure:**
1. Go to **Tools** in the left sidebar
2. Click **"Webhooks"**
3. Click **"Add Webhook"**
4. Enter the webhook URL (provided by the app you're connecting to)
5. Choose what information to send (customer name, email, message, etc.)
6. Choose when to send it (after booking, after feedback, etc.)
7. Click **"Save"**

**Example - Sending Leads to a CRM:**
When a customer provides their name and email to book an appointment, the webhook sends that information to your CRM so your team can follow up.

**Example - Slack Notification:**
When a customer leaves negative feedback, a webhook sends a message to your team's Slack channel so someone can follow up immediately.

---

### Custom API Integrations

For businesses that use custom software, you can connect your agent to any system with an API.

**What is an API?**
An API is a way for different software systems to talk to each other. If you use custom software for your business (like a custom booking system or inventory manager), an API integration lets your agent interact with it.

**Use cases:**
- Check real-time inventory
- Look up customer accounts in your custom database
- Create orders in your custom order management system
- Check loyalty points or rewards

**How to configure:**
1. Go to **Tools** in the left sidebar
2. Click **"Custom API"**
3. Enter your API endpoint URL
4. Choose the request method (GET to retrieve information, POST to send information)
5. Set up the data format (what information to send and what to expect back)
6. Test the connection
7. Click **"Save"**

> **Note:** Custom API integrations require some technical knowledge. If you're not comfortable setting this up, ask your developer or contact our support team for assistance.

---

## When to Use Tools vs. Playbooks

This is a common question. Here's a simple way to think about it:

### Use a Playbook When:
- You want to guide a conversation
- You need the agent to ask questions and respond to answers
- The scenario is informational (answering FAQs, explaining policies)
- No external action is needed

### Use a Tool When:
- You need the agent to take a real-world action
- The action involves another system (calendar, email, payment)
- You need to send or receive data from another service
- You want to automate a task that would otherwise require a human

### Use Both Together When:
- You want a guided conversation that ends with an action
- Example: A booking playbook guides the conversation, and the calendar tool creates the event
- Example: A feedback playbook collects the review, and the email tool sends it to your team

---

## Tool Configuration Best Practices

### 1. Start Simple

Connect one tool at a time. Start with the most important one for your business:
- If you take appointments: Start with Calendar
- If you sell online: Start with Payments
- If you communicate with customers: Start with Email or SMS

### 2. Test Every Tool

After connecting a tool, test it:
- For Calendar: Book a test appointment and check that it appears in your calendar
- For Email: Send a test email and check that it arrives
- For SMS: Send a test text message to your phone
- For Payments: Process a small test payment (most providers offer a test mode)

### 3. Monitor Tool Usage

Check your dashboard regularly to see:
- How many emails your agent has sent
- How many appointments have been booked
- How many payments have been processed
- Any errors or failed actions

### 4. Keep Credentials Secure

- Never share your API keys or authentication tokens
- If a team member leaves, review and rotate credentials
- Use test modes when available during setup

---

## Common Tool Combinations by Business Type

### Dental Clinic
- **Calendar** - Book patient appointments
- **SMS** - Send appointment reminders
- **Email** - Send confirmations and follow-ups

### Pizza Shop
- **Payments** - Collect orders and payments
- **SMS** - Send order confirmations and delivery updates
- **Webhook** - Send orders to your kitchen display system

### Hair Salon
- **Calendar** - Book client appointments
- **Email** - Send booking confirmations and style tips
- **SMS** - Send reminders and promotional offers

### Retail Store
- **Payments** - Process online orders
- **Webhook** - Update inventory system
- **Email** - Send order confirmations and shipping updates

### Consulting Firm
- **Calendar** - Book client consultations
- **Email** - Send meeting agendas and follow-ups
- **Payments** - Collect consultation fees or deposits

---

## Troubleshooting Common Issues

### Calendar Not Showing Availability
- Check that your working hours are set correctly
- Make sure your calendar is connected and authorized
- Verify that there are no conflicting events in your calendar

### Emails Not Sending
- Check that your email provider is connected
- Verify the recipient email address is correct
- Check your email provider's sending limits

### SMS Not Delivering
- Verify your phone number is connected and verified
- Check that the customer's phone number is in the correct format
- Review your SMS provider's delivery status

### Payments Failing
- Check that your payment provider account is active
- Verify your bank account is linked correctly
- Review the payment provider's dashboard for error messages

### Webhooks Not Triggering
- Verify the webhook URL is correct
- Check that the receiving service is online
- Review the webhook logs for error messages

---

## What's Next?

Now that your tools are configured:
- **Voice Setup** - Let customers call your agent and use these tools over the phone
- **Playbooks** - Create conversation flows that use your tools
- **Team** - Invite team members to help manage your tools and integrations
