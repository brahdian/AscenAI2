# Agent Configuration

Make your AI agent sound like it belongs to your business. This guide covers every setting you can customize.

---

## Agent Name and Identity

Your agent's name is the first thing customers see. Choose something that fits your business.

### Naming Guidelines

**Match your business style:**
- Professional services (dentists, lawyers, clinics): Use formal names like "Reception Assistant" or "Patient Coordinator"
- Casual businesses (restaurants, shops, salons): Use friendly names like "Order Helper" or "Style Advisor"
- Personal brands: Use your name with a role, like "Sarah's Assistant" or "Mike's Booking Bot"

**What to avoid:**
- Generic names like "Chatbot" or "AI Assistant"
- Names that are too long or hard to spell
- Names that don't match your brand voice

### Agent Role Description

The role description is the most important setting. It tells your agent who it is and what it should do.

**Think of it like training a new employee.** The more specific you are, the better results you'll get.

**Template:**
```
You are a [role] for [business name]. You help customers with [main tasks]. 
Your tone should be [tone]. You should [specific behaviors]. 
You should NOT [things to avoid].
```

**Example - Dental Clinic:**
```
You are a friendly receptionist for Smile Bright Dental Clinic. You help patients 
book appointments, answer questions about our services, and provide office hours 
and location information. Your tone should be warm and professional. Always ask 
if they'd like to book an appointment after answering their question. You should 
NOT give medical advice or discuss specific treatments.
```

**Example - Pizza Shop:**
```
You are a helpful order assistant for Tony's Pizza. You help customers place 
orders, answer questions about our menu, and provide delivery information. Your 
tone should be casual and enthusiastic. Always suggest our daily special. You 
should NOT promise delivery times during busy hours or discuss ingredients you 
don't have information about.
```

**Example - Hair Salon:**
```
You are a style advisor for Serenity Salon. You help clients book appointments, 
learn about our services, and choose the right treatment for their needs. Your 
tone should be friendly and knowledgeable. Always mention our first-visit discount. 
You should NOT recommend specific hairstyles without knowing the client's hair type.
```

---

## Greeting Message

The greeting message is what customers see the moment they open the chat widget.

### What Makes a Good Greeting

A good greeting does three things:
1. Welcomes the customer
2. Identifies your business
3. Invites them to ask a question

### Examples by Business Type

**Dental Clinic:**
> "Hi! Welcome to Smile Bright Dental. How can I help you today? I can answer questions about our services, check our availability, or help you book an appointment."

**Pizza Shop:**
> "Hey there! Thanks for visiting Tony's Pizza. Hungry? I can help you place an order, check our menu, or answer any questions about delivery."

**Hair Salon:**
> "Hello! Welcome to Serenity Salon. I'm here to help you book your next appointment or answer any questions about our services. What can I do for you?"

**Law Firm:**
> "Good day. Thank you for contacting Morrison & Associates. How may I assist you? I can provide information about our practice areas or help you schedule a consultation."

### Best Practices

- Keep it under 3 sentences
- Match your business tone (formal, casual, friendly)
- Mention 2-3 things the agent can help with
- Avoid generic greetings like "How can I help?" without context
- Update it seasonally or during promotions ("Happy Holidays! Ask about our New Year special!")

---

## Voice Settings

If your agent handles phone calls, voice settings determine how it sounds.

### Language

Choose the primary language your agent will speak.

- **English** - Default, supports American, British, Australian, and other accents
- **French** - For Canadian and French businesses
- **Spanish** - For businesses serving Spanish-speaking communities
- **Hindi, Mandarin, Arabic** - Available on Growth and Scale plans

> **Tip:** If your customers speak multiple languages, you can create separate agents for each language and embed them on different pages of your website.

### Voice Selection

Choose from a variety of natural-sounding voices. You can preview each voice before selecting.

**Voice categories:**
- **Professional** - Clear, formal voices good for clinics, law firms, and financial services
- **Friendly** - Warm, conversational voices good for restaurants, salons, and retail
- **Energetic** - Upbeat voices good for fitness centers, entertainment, and youth-oriented businesses

### Voice Speed

Adjust how fast your agent speaks:
- **Slow** - Good for older customers or complex information
- **Normal** - Default, works for most situations
- **Fast** - Good for quick confirmations and simple interactions

---

## Personality and Tone

Your agent's personality shapes how it responds to customers.

### Tone Settings

Choose the overall tone that matches your brand:

| Tone | Best For | Example Response |
|------|----------|------------------|
| Professional | Law firms, clinics, financial services | "I'd be happy to help you schedule a consultation." |
| Friendly | Restaurants, salons, retail | "Sure thing! Let me help you with that!" |
| Casual | Food trucks, bars, youth brands | "No worries, I got you covered!" |
| Enthusiastic | Fitness, entertainment, events | "That's awesome! Let's get you set up!" |

### Custom Personality Instructions

You can add specific personality traits in the agent role description:

- "Always be patient and explain things clearly"
- "Use humor when appropriate, but stay respectful"
- "Be brief and direct - our customers are in a hurry"
- "Always thank the customer at the end of the conversation"
- "Use the customer's name if they provide it"

### What to Avoid

- Overly casual language for professional services
- Robotic or overly formal language for casual businesses
- Making promises you can't keep ("We'll definitely fix this today!")
- Using slang or jargon your customers won't understand

---

## Guardrails

Guardrails are rules that tell your agent what NOT to do. They protect your business from mistakes and keep conversations on track.

### Why Guardrails Matter

Without guardrails, your agent might:
- Give incorrect information about pricing
- Promise services you don't offer
- Share sensitive business information
- Handle complaints inappropriately
- Go off-topic for too long

### Common Guardrails

**Information Guardrails:**
- "Do not provide pricing information not found in the knowledge base"
- "Do not discuss competitor businesses"
- "Do not share internal company information"

**Behavior Guardrails:**
- "Do not make promises about delivery times"
- "Do not offer discounts not listed in the knowledge base"
- "Do not argue with customers - always stay polite"

**Scope Guardrails:**
- "If asked about topics outside your knowledge, say: 'I'm not sure about that. Let me connect you with someone who can help.'"
- "If a customer is upset, apologize and offer to have a team member follow up"
- "If asked for medical or legal advice, direct them to speak with a professional"

### Setting Guardrails

1. In your agent settings, go to the **"Guardrails"** tab
2. Click **"Add Guardrail"**
3. Type your rule in plain language
4. Click **"Save"**

**Examples for different businesses:**

**Dental Clinic:**
- "Do not provide medical diagnoses or treatment recommendations"
- "Do not discuss other patients' information"
- "If asked about insurance, direct them to call our office for verification"

**Pizza Shop:**
- "Do not promise specific delivery times during peak hours (5-9 PM)"
- "Do not offer custom menu items not listed in the knowledge base"
- "If a customer complains about food quality, apologize and offer to have a manager call them"

**Hair Salon:**
- "Do not recommend chemical treatments without an in-person consultation"
- "Do not discuss pricing for services not listed on our menu"
- "If a customer requests a stylist who is unavailable, offer alternative times or stylists"

---

## Knowledge Base

Your knowledge base is where you upload information about your business. This is how your agent learns what to say.

### What to Upload

Think about what your customers ask most often. Upload documents that answer those questions.

**Common documents to upload:**

| Document Type | Example Content |
|---------------|-----------------|
| FAQ document | Answers to your 20 most common customer questions |
| Price list | All your services and their prices |
| Menu | Full menu with descriptions and prices |
| Service descriptions | Detailed explanations of what you offer |
| Office hours | When you're open, holiday schedules |
| Location info | Address, parking instructions, directions |
| Policies | Cancellation, refund, return policies |
| Staff bios | Information about your team members |

### How to Upload

1. In your agent settings, click the **"Knowledge Base"** tab
2. Click **"Upload Documents"**
3. Select files from your computer
4. Wait for the upload to complete (you'll see a progress bar)
5. Your documents are automatically processed and ready to use

**Supported file types:**
- PDF files
- Word documents (.doc, .docx)
- Text files (.txt)
- CSV files (for price lists, schedules, etc.)

### Organizing Your Knowledge

**Tips for better results:**

- **Use clear headings** - Your agent uses headings to find information quickly
- **Keep documents focused** - One topic per document works best
- **Update regularly** - When prices or hours change, upload the new version
- **Remove outdated documents** - Old information can confuse your agent

### Example: Building a Knowledge Base for a Dental Clinic

1. **FAQs.pdf** - Answers to: Do you take new patients? What insurance do you accept? Do you offer payment plans? What should I do in a dental emergency?
2. **Services.pdf** - Descriptions of: Cleanings, fillings, crowns, whitening, implants, orthodontics
3. **Pricing.pdf** - Cost of each service, insurance co-pay information
4. **Hours.pdf** - Regular hours, holiday schedule, emergency contact info
5. **Location.pdf** - Address, parking info, public transit directions, nearby landmarks
6. **Policies.pdf** - Cancellation policy (24-hour notice), late arrival policy, children's policy

### Example: Building a Knowledge Base for a Pizza Shop

1. **Menu.pdf** - Full menu with sizes, toppings, prices, combo deals
2. **FAQs.pdf** - Delivery area, delivery fee, minimum order, payment methods
3. **Hours.pdf** - Open hours, holiday schedule, catering availability
4. **Allergens.pdf** - Gluten-free options, nut-free kitchen info, vegan options
5. **Catering.pdf** - Party packages, minimum order, advance notice required

---

## Testing Your Configuration

After setting up your agent, test it thoroughly.

### Testing Checklist

- [ ] Ask about business hours
- [ ] Ask about pricing for a specific service
- [ ] Try to book an appointment
- [ ] Ask a question NOT covered in your knowledge base
- [ ] Ask about a topic your guardrails should block
- [ ] Test the greeting message by opening the widget
- [ ] Check that the tone matches your brand

### How to Test

1. Click the **"Preview"** button in your agent settings
2. Type questions as if you were a customer
3. Review the responses for accuracy and tone
4. Make adjustments and test again

### When to Revisit Your Configuration

- **Monthly** - Review chat history and update knowledge base
- **When prices change** - Update pricing documents immediately
- **When you add services** - Upload new service descriptions
- **When customers ask questions your agent can't answer** - Add that information to your knowledge base
- **Seasonally** - Update hours, promotions, and greeting messages
