# Compliance & Privacy

Protect your customers' data and stay compliant with privacy laws.

---

## Why Privacy Matters

Your AI agent handles customer conversations that may include personal information like names, phone numbers, email addresses, and appointment details. Protecting this information is not just good practice - it's the law in many regions.

This guide covers the privacy regulations that may apply to your business and how AscenAI2 helps you comply.

---

## PIPEDA (Canadian Privacy Law)

### What Is PIPEDA?

PIPEDA stands for the Personal Information Protection and Electronic Documents Act. It's Canada's federal privacy law for private-sector organizations.

**Who needs to comply:**
- Businesses operating in Canada
- Businesses that collect personal information from Canadian residents
- This includes businesses of all sizes - even small businesses like dental clinics, restaurants, and salons

### What PIPEDA Requires

**1. Consent**
- You must get customer consent before collecting their personal information
- Customers should know what information you're collecting and why
- Consent can be explicit (checking a box) or implied (using your service)

**How AscenAI2 helps:**
- Your agent can be configured to inform customers that their conversation is being processed by an AI
- You can add a consent message at the start of conversations

**2. Purpose**
- You must identify the purpose for collecting personal information
- You can only use the information for the stated purpose

**How AscenAI2 helps:**
- You control what information your agent collects
- You can configure your agent to only collect information necessary for the service

**3. Safeguards**
- You must protect personal information with appropriate security measures

**How AscenAI2 helps:**
- All data is encrypted in transit and at rest
- Access controls ensure only authorized team members can view conversations
- Regular security audits are conducted

**4. Access**
- Customers have the right to access their personal information
- Customers can request corrections to their information

**How AscenAI2 helps:**
- You can export customer data from your dashboard
- You can delete customer data upon request

**5. Retention**
- Personal information should only be kept as long as necessary

**How AscenAI2 helps:**
- You can set automatic data retention periods
- Old conversations can be automatically deleted

### PIPEDA Compliance Checklist

- [ ] Inform customers that their conversation is handled by AI
- [ ] Only collect information necessary for the service
- [ ] Set appropriate data retention periods
- [ ] Have a process for handling customer data access requests
- [ ] Have a process for handling customer data deletion requests
- [ ] Train your team on privacy responsibilities
- [ ] Keep records of consent

---

## GDPR (European Privacy Law)

### What Is GDPR?

GDPR stands for the General Data Protection Regulation. It's the European Union's privacy law, but it applies to any business that handles data of EU residents, regardless of where your business is located.

**Who needs to comply:**
- Businesses operating in the EU
- Businesses that offer goods or services to EU residents
- Businesses that monitor the behavior of EU residents

### Key GDPR Requirements

**1. Lawful Basis**
- You must have a lawful reason to process personal data
- Common lawful bases: consent, contract performance, legitimate interest

**2. Data Minimization**
- Only collect data that is necessary for your stated purpose
- Don't collect "just in case" data

**3. Right to Be Forgotten**
- Customers can request that you delete all their personal data
- You must comply within 30 days

**4. Data Portability**
- Customers can request a copy of their data in a usable format
- You must provide it within 30 days

**5. Breach Notification**
- If customer data is compromised, you must notify affected individuals within 72 hours

### How AscenAI2 Helps with GDPR

- **Data export** - Export customer data in standard formats
- **Data deletion** - Delete individual customer data or all data
- **Retention settings** - Automatically delete old data
- **Consent management** - Configure consent messages in your agent
- **Access controls** - Limit who can view customer data

---

## Data Retention Settings

Control how long customer conversations and data are stored.

### Why Set Retention Periods?

- **Privacy compliance** - Many laws require you to delete data when it's no longer needed
- **Security** - Less stored data means less data at risk in a breach
- **Cost management** - Some plans charge based on data storage
- **Customer trust** - Shows customers you respect their privacy

### Setting Your Retention Period

1. Go to **Settings** > **Privacy**
2. Click the **"Data Retention"** tab
3. Choose your retention period:
   - **30 days** - Conversations deleted after 30 days
   - **90 days** - Conversations deleted after 90 days
   - **6 months** - Conversations deleted after 6 months
   - **1 year** - Conversations deleted after 1 year
   - **Indefinite** - Conversations kept until manually deleted

4. Click **"Save"**

### What Gets Deleted

When the retention period expires:
- Chat conversation transcripts are deleted
- Voice call recordings are deleted
- Customer contact information from conversations is deleted

**What is NOT deleted:**
- Analytics data (aggregated, non-identifiable statistics)
- Your agent configurations and playbooks
- Your knowledge base documents
- Team member accounts

### Recommended Retention Periods by Business Type

| Business Type | Recommended Retention | Reason |
|---------------|----------------------|--------|
| Dental clinic | 1 year | Patient records may be needed for follow-up |
| Restaurant | 30 days | Orders and inquiries are short-term |
| Hair salon | 90 days | Appointment history useful for scheduling |
| Law firm | 1 year or more | Client matters may require record keeping |
| Retail store | 90 days | Order history for returns and support |
| Fitness center | 6 months | Membership and booking history |

---

## Exporting Your Data

You can export your data at any time for backup, analysis, or compliance purposes.

### What You Can Export

**Chat History**
- All conversation transcripts
- Customer messages and agent responses
- Timestamps and duration
- Customer satisfaction ratings

**Voice Call History**
- Call recordings (if enabled)
- Call duration and timestamps
- Transcripts of voice conversations

**Customer Data**
- Names, emails, phone numbers collected during conversations
- Booking history
- Payment history

**Analytics**
- Conversation volume by day/week/month
- Most common topics
- Customer satisfaction trends
- Tool usage statistics

### How to Export

1. Go to **Settings** > **Privacy**
2. Click the **"Export Data"** tab
3. Choose what data to export:
   - Chat history
   - Voice recordings
   - Customer data
   - Analytics
4. Choose the date range
5. Choose the format (CSV or JSON)
6. Click **"Export"**
7. You'll receive an email when the export is ready
8. Download the file from the link in the email

### Export Format

**CSV** - Best for viewing in spreadsheets (Excel, Google Sheets)
- Easy to read and analyze
- Good for customer lists and conversation summaries

**JSON** - Best for technical use
- Structured data format
- Good for importing into other systems
- Contains all data fields

---

## Deleting Customer Data

### Deleting Individual Customer Data

If a customer requests that their data be deleted:

1. Go to **Chat History** in your dashboard
2. Search for the customer by name, email, or phone number
3. Click on a conversation with that customer
4. Click the three dots in the top right
5. Click **"Delete Customer Data"**
6. Confirm the deletion

This deletes:
- All conversations with that customer
- Any contact information associated with that customer
- Any recordings of voice calls with that customer

### Deleting All Data

If you need to delete all customer data (for example, when closing your business):

1. Go to **Settings** > **Privacy**
2. Click the **"Delete All Data"** tab
3. Read the warning carefully - this cannot be undone
4. Type "DELETE ALL DATA" to confirm
5. Click **"Delete"**

This deletes:
- All chat conversation transcripts
- All voice call recordings
- All customer contact information
- All analytics data

This does NOT delete:
- Your agent configurations
- Your playbooks
- Your knowledge base documents
- Your team members
- Your account itself

---

## Customer Consent

### Adding Consent Messages

You can configure your agent to inform customers about data processing at the start of conversations.

**How to set up:**
1. Go to your **Agent Settings**
2. Click the **"Privacy"** tab
3. Toggle **"Show consent message"** to on
4. Customize the consent message

**Example consent messages:**

**Chat:**
> "Hi! I'm an AI assistant for [Business]. Your conversation with me is processed securely to help answer your questions. By continuing, you consent to this processing. How can I help you today?"

**Voice:**
> "Thank you for calling [Business]. This call is handled by an AI assistant. Your conversation is processed securely to help serve you. How can I help you today?"

### Cookie Consent

If you embed the chat widget on your website, it may use cookies. Make sure your website's cookie policy mentions the chat widget.

**Example addition to your cookie policy:**
> "Our website uses a chat widget powered by AscenAI2. This widget may use cookies to remember your session and improve your experience. For more information, see AscenAI2's privacy policy."

---

## Team Privacy Responsibilities

Everyone on your team who has access to customer data has privacy responsibilities.

### Owner and Admin Responsibilities

- Set appropriate data retention periods
- Ensure team members understand privacy obligations
- Handle customer data access and deletion requests
- Review access logs periodically
- Ensure compliance with applicable privacy laws

### Developer Responsibilities

- Only access customer data when necessary for technical work
- Never copy or export customer data without authorization
- Report any suspected data breaches immediately
- Follow security best practices when setting up integrations

### Viewer Responsibilities

- Only view customer data for legitimate business purposes
- Never share customer information outside the organization
- Report any concerns about data handling to the owner or admin

---

## Data Breach Response

If you suspect customer data has been compromised:

### Immediate Steps

1. **Don't panic** - AscenAI2 has security measures in place
2. **Contact support** - Email security@ascenai.com immediately
3. **Document what happened** - Write down what you noticed and when
4. **Don't delete evidence** - Keep any logs or screenshots

### AscenAI2's Response

- Our security team will investigate
- We'll determine what data was affected
- We'll notify you of the findings
- We'll help you meet any notification obligations

### Your Obligations

Depending on the applicable law:
- **PIPEDA** - Report breaches to the Privacy Commissioner if there's a real risk of significant harm
- **GDPR** - Report breaches to your supervisory authority within 72 hours
- **Both** - Notify affected individuals if there's a risk to their rights and freedoms

---

## Privacy Best Practices

### 1. Collect Only What You Need

Don't ask customers for information you don't need. If you only need a name and phone number to book an appointment, don't also ask for their email and address.

### 2. Be Transparent

Tell customers when they're talking to an AI. Tell them what information you're collecting and why.

### 3. Set Appropriate Retention

Don't keep customer data longer than necessary. Set retention periods that match your business needs and legal requirements.

### 4. Train Your Team

Make sure everyone who has access to customer data understands their responsibilities.

### 5. Have a Process

Have a clear process for handling customer data requests (access, deletion, correction).

### 6. Review Regularly

Review your privacy settings and practices at least annually, or whenever you make significant changes to your agent.

---

## AscenAI2's Privacy Commitments

As a user of AscenAI2, you can be confident that:

- **Encryption** - All data is encrypted in transit (while being sent) and at rest (while stored)
- **Access controls** - Only authorized AscenAI2 personnel can access infrastructure, and only when necessary
- **No training on your data** - Your customer conversations are NOT used to train AI models
- **Regular audits** - Our systems are regularly audited for security and compliance
- **Data processing agreement** - We provide a Data Processing Agreement (DPA) for customers who need one
- **Subprocessors** - We maintain a list of all subprocessors (like Twilio for voice) and notify you of changes

---

## What's Next?

Now that you understand compliance and privacy:
- Review your **data retention settings** and make sure they're appropriate for your business
- Set up **consent messages** for your agent
- Train your **team** on their privacy responsibilities
- Create a process for handling **customer data requests**

For questions about compliance, contact our support team at **support@ascenai.com** or consult with a privacy professional in your jurisdiction.
