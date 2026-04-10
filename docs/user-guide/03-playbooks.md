# Playbooks

Create conversation scripts that guide your agent through specific scenarios. Think of playbooks as response templates for the situations your business handles most often.

---

## What Is a Playbook?

A playbook is a set of instructions that tells your agent how to handle a specific type of conversation.

**Think of it this way:** If your agent is a new employee, a playbook is the training manual for a specific task. Just like you'd train an employee on how to handle a booking request differently from a complaint, you create different playbooks for different scenarios.

### Examples of When to Use Playbooks

- A customer wants to **book an appointment**
- A customer asks about **pricing**
- A customer wants to **leave feedback**
- A customer asks about your **return policy**
- A customer wants to **cancel or reschedule**
- A customer asks about **delivery areas**

### Playbooks vs. Knowledge Base

| Knowledge Base | Playbooks |
|----------------|-----------|
| General information about your business | Step-by-step conversation flows |
| Answers "what" questions | Guides customers through a process |
| Static documents | Interactive conversations |
| Example: "Our hours are 9-5" | Example: "When would you like to come in?" |

You need both. The knowledge base gives your agent facts. Playbooks give your agent a process to follow.

---

## Playbook Structure

Every playbook has three parts:

### 1. Triggers

Triggers tell your agent when to use this playbook. These are the words or phrases that activate it.

**Example - Booking Playbook Triggers:**
- "book an appointment"
- "schedule a visit"
- "make a reservation"
- "I'd like to come in"
- "are you available"

**Example - Pricing Playbook Triggers:**
- "how much"
- "what does it cost"
- "pricing"
- "what are your rates"

### 2. Responses

Responses are what your agent says during the conversation. You can set up multiple responses that flow together.

**Example - Booking Playbook Responses:**

**Response 1:** "I'd be happy to help you book an appointment! What day works best for you?"

**Response 2:** "Great! We have availability on [day] at [times]. Which time would you prefer?"

**Response 3:** "Perfect! I just need your name and phone number to confirm. Can you provide those?"

**Response 4:** "Thank you! Your appointment is confirmed for [day] at [time]. We'll send you a reminder text the day before. Is there anything else I can help with?"

### 3. Actions

Actions are things your agent does during the conversation, like sending a confirmation email or adding an event to your calendar.

**Example - Booking Playbook Actions:**
- Send a confirmation email to the customer
- Add the appointment to your calendar
- Send an SMS reminder to the customer
- Notify your team via email

---

## How to Create a Playbook

### Step 1: Go to Playbooks

1. From your dashboard, click **"Playbooks"** in the left sidebar
2. Click **"Create Playbook"** in the top right

### Step 2: Name Your Playbook

Give it a clear name that describes what it does:
- "Appointment Booking"
- "FAQ Response"
- "Customer Feedback Collection"
- "Order Status Check"

### Step 3: Set Triggers

1. In the **"Triggers"** section, type the words or phrases that should activate this playbook
2. Press Enter after each trigger
3. Add as many triggers as you think customers might use

**Tip:** Think about the different ways customers might ask for the same thing. Some people say "book," others say "schedule," and others say "make an appointment."

### Step 4: Write Responses

1. In the **"Responses"** section, click **"Add Response"**
2. Type the message your agent should say
3. Add follow-up responses for each step of the conversation
4. Use the **"Connect Responses"** feature to link them in order

**Tip:** Write responses the way you'd actually talk to a customer. Read them out loud to check if they sound natural.

### Step 5: Add Actions (Optional)

1. In the **"Actions"** section, click **"Add Action"**
2. Choose the action type (send email, book calendar, send SMS, etc.)
3. Configure the action details
4. Choose when the action should happen (after a specific response, at the end of the conversation, etc.)

### Step 6: Save and Test

1. Click **"Save Playbook"**
2. Go to your agent's **Preview** window
3. Type one of your triggers to test the playbook
4. Walk through the entire conversation to make sure it flows correctly

---

## Playbook Examples

### Example 1: Appointment Booking (Dental Clinic)

**Name:** Appointment Booking

**Triggers:**
- book appointment
- schedule a visit
- make an appointment
- when are you available
- I need to see the dentist

**Responses:**

1. "I'd be happy to help you book an appointment at Smile Bright Dental! Are you a new patient or have you visited us before?"

2. "Great! What day of the week works best for you? We're open Monday through Friday from 9 AM to 5 PM, and Saturdays from 9 AM to 1 PM."

3. "Let me check our availability. We have openings on [day] at [time slots]. Which works best for you?"

4. "Perfect! I just need a few details to confirm your appointment:
   - Your full name
   - Phone number
   - Are you coming in for a cleaning, or do you have a specific concern?"

5. "Thank you! Your appointment is confirmed for [day] at [time]. We'll send you a text reminder 24 hours before. Please arrive 10 minutes early to fill out any necessary paperwork. Is there anything else I can help with?"

**Actions:**
- Add appointment to Google Calendar
- Send confirmation email to customer
- Send SMS reminder 24 hours before appointment

---

### Example 2: FAQ Response (Pizza Shop)

**Name:** Delivery FAQ

**Triggers:**
- delivery area
- do you deliver
- how far do you deliver
- delivery fee
- minimum order for delivery

**Responses:**

1. "Yes, we deliver! Our delivery area covers everything within 5 miles of our location on Main Street. Would you like to check if we deliver to your address?"

2. "Our delivery fee is $3.99 for orders under $30, and FREE for orders over $30. We also have a $15 minimum order for delivery."

3. "Delivery usually takes 30-45 minutes, but it can be a bit longer during dinner rush (5-8 PM) or on weekends. Would you like to place an order now?"

**Actions:**
- None needed (informational playbook)

---

### Example 3: Customer Feedback Collection (Hair Salon)

**Name:** Feedback Collection

**Triggers:**
- leave feedback
- I want to review
- how was my service
- customer satisfaction
- rate my experience

**Responses:**

1. "We'd love to hear about your experience at Serenity Salon! On a scale of 1 to 5, how would you rate your visit today?"

2. "Thank you for that rating! Is there anything specific you'd like to share about your experience? Your feedback helps us improve."

3. "We really appreciate your feedback! As a thank you, here's a 10% discount code for your next visit: THANKYOU10. Would you like to book your next appointment while you're here?"

**Actions:**
- Send feedback summary to salon manager via email
- If rating is 3 or below, send alert to manager for follow-up

---

### Example 4: Order Status Check (Retail Store)

**Name:** Order Status

**Triggers:**
- where is my order
- order status
- track my order
- when will my order arrive
- check order

**Responses:**

1. "I can help you check your order status! Could you please provide your order number? You'll find it in the confirmation email we sent you."

2. "Thanks! Let me look that up for you... Your order #[number] is currently [status: processing/shipped/out for delivery]. The expected delivery date is [date]."

3. "Is there anything else I can help you with regarding your order? If you have any other questions, feel free to ask!"

**Actions:**
- Call webhook to check order status in your system
- Send tracking information via email if requested

---

## Best Practices for Writing Effective Playbooks

### 1. Keep It Conversational

Write responses the way you'd actually talk to a customer. Avoid robotic or overly formal language unless that matches your brand.

**Good:** "Sure! I can help you with that. What day works best?"
**Bad:** "Acknowledged. Please specify the desired date for your appointment."

### 2. Ask One Question at a Time

Don't overwhelm customers with multiple questions in one message.

**Good:** "What day works best for you?" (then in the next response) "What time would you prefer?"
**Bad:** "What day and time would you like to come in? Also, what's your name, phone number, and email?"

### 3. Always Offer Next Steps

End each playbook with a clear next step or an offer to help further.

**Examples:**
- "Would you like to book your appointment now?"
- "Is there anything else I can help you with?"
- "Would you like me to send that information to your email?"

### 4. Handle Dead Ends

What if the customer says something unexpected? Add a fallback response.

**Example:** "I'm not sure I understood. Could you rephrase that? Or would you like to speak with a team member instead?"

### 5. Test with Real Scenarios

Test your playbooks using the actual questions your customers ask. Review your chat history to find common patterns.

### 6. Keep Playbooks Focused

One playbook per scenario. Don't try to handle bookings, complaints, and pricing in the same playbook.

### 7. Update Regularly

Review your playbooks monthly. If customers are asking questions your playbooks don't cover, create new ones.

---

## Testing Playbooks

### Before Going Live

1. Open your agent's **Preview** window
2. Type each trigger you set up
3. Walk through the entire conversation flow
4. Check that:
   - Responses sound natural
   - The conversation flows logically
   - Actions trigger correctly (emails sent, calendar events created, etc.)
   - Fallback responses work for unexpected inputs

### After Going Live

1. Review chat history weekly
2. Look for conversations where the playbook didn't work as expected
3. Adjust responses or add new triggers based on real customer language
4. Check that actions (emails, calendar events) are being created correctly

### Common Issues and Fixes

| Issue | Fix |
|-------|-----|
| Playbook doesn't activate | Add more trigger variations that customers actually use |
| Responses feel robotic | Rewrite in a more conversational tone |
| Conversation gets stuck | Add fallback responses for unexpected inputs |
| Actions don't trigger | Check that the tool is properly connected and configured |
| Playbook activates when it shouldn't | Make triggers more specific |

---

## How Many Playbooks Do You Need?

Start with 2-3 playbooks for your most common scenarios. Add more as you learn what your customers ask.

**Recommended starting playbooks:**
1. **Appointment/Booking** - If you take appointments
2. **FAQ** - For your most common questions
3. **Feedback** - To collect customer reviews

**Add later:**
- Order status tracking
- Cancellation/rescheduling
- Complaint handling
- Upselling/cross-selling
- Event registration

---

## What's Next?

Now that you've created playbooks, explore:
- **Tools** - Give your agent the ability to take real actions like sending emails and booking appointments
- **Voice Setup** - Let your agent handle phone calls using the same playbooks
- **Team** - Invite team members to help manage and improve your playbooks
