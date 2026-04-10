# Team & Permissions

Invite your team to collaborate on building and managing your AI agents.

---

## Why Add Team Members?

Your AI agent is only as good as the information and effort you put into it. Adding team members lets you:

- Share the workload of building and improving your agent
- Let subject matter experts contribute knowledge (your receptionist knows what patients ask most)
- Give developers access to set up integrations without giving them full account access
- Keep an eye on performance with viewer access for managers

---

## Adding Team Members

### Step 1: Go to Team Settings

1. In your dashboard, click **"Settings"** in the left sidebar
2. Click the **"Team"** tab

### Step 2: Invite a Member

1. Click **"Invite Member"** in the top right
2. Enter the person's email address
3. Choose their role (Owner, Admin, Developer, or Viewer)
4. Add an optional message (e.g., "Welcome to the team! Here's access to our AI agent.")
5. Click **"Send Invitation"**

### Step 3: They Accept

The person will receive an email invitation with a link to join your workspace. Once they accept, they'll appear in your team list.

### Managing Existing Members

- **Change role** - Click the dropdown next to their name and select a new role
- **Remove member** - Click the three dots next to their name and select "Remove"
- **Resend invitation** - If they haven't accepted, click "Resend Invitation"

---

## Roles and Permissions

### Owner

The owner has full control over everything in the account.

**What Owners Can Do:**
- Manage all agents, playbooks, tools, and settings
- Add and remove team members
- Change roles for any team member
- Manage billing and payment methods
- Delete the account
- Access all API keys
- View all chat history and analytics
- Export all data

**Who Should Be an Owner:**
- The business owner
- The person who pays for the account
- The primary decision-maker for the AI agent strategy

> **Note:** There can only be one owner per account. You can transfer ownership to another team member if needed.

### Admin

Admins have nearly full control, with a few restrictions.

**What Admins Can Do:**
- Create, edit, and delete agents
- Create and manage playbooks
- Connect and configure tools
- View chat history and analytics
- Invite new team members (except other admins)
- Manage API keys (create and revoke)
- Export data
- View billing information (but not change payment methods)

**What Admins Cannot Do:**
- Delete the account
- Change the account owner
- Change payment methods or billing information
- Remove the owner
- Invite other admins

**Who Should Be an Admin:**
- Marketing managers
- Operations managers
- Senior team members who manage the agent day-to-day

### Developer

Developers have technical access for setting up integrations.

**What Developers Can Do:**
- Create and edit agents
- Create and manage playbooks
- Connect and configure tools (including webhooks and custom APIs)
- View and manage API keys
- Test agents in preview mode
- View chat history (for debugging)
- View analytics

**What Developers Cannot Do:**
- Manage team members
- Access billing information
- Delete agents (only edit)
- Export data
- Change account settings

**Who Should Be a Developer:**
- Web developers who embed the widget
- IT staff who set up integrations
- Freelancers or agencies managing your technical setup

### Viewer

Viewers can see everything but change nothing.

**What Viewers Can Do:**
- View agents and their settings
- View playbooks
- View connected tools
- View chat history
- View analytics and reports
- Export data (if enabled by admin)

**What Viewers Cannot Do:**
- Make any changes to agents, playbooks, or tools
- Manage team members
- Access API keys
- Access billing
- Delete anything

**Who Should Be a Viewer:**
- Business partners who want to monitor performance
- Managers who review customer interactions
- Consultants who audit your AI agent performance
- New team members who are learning the system

---

## Role Comparison Table

| Permission | Owner | Admin | Developer | Viewer |
|------------|-------|-------|-----------|--------|
| Create/edit agents | Yes | Yes | Yes | No |
| Delete agents | Yes | Yes | No | No |
| Manage playbooks | Yes | Yes | Yes | No |
| Connect tools | Yes | Yes | Yes | No |
| Manage team | Yes | Partial | No | No |
| View billing | Yes | View only | No | No |
| Change payment | Yes | No | No | No |
| Manage API keys | Yes | Yes | Yes | No |
| View chat history | Yes | Yes | Yes | Yes |
| View analytics | Yes | Yes | Yes | Yes |
| Export data | Yes | Yes | No | Partial |
| Delete account | Yes | No | No | No |

---

## Managing API Keys

API keys allow external systems to interact with your AscenAI2 account. They're used for custom integrations, webhooks, and connecting to other software.

### What Are API Keys?

Think of an API key like a password that lets another system talk to your AscenAI2 account. You might need one if:

- A developer is building a custom integration
- You're connecting your agent to your CRM
- You want to pull chat data into your own dashboard
- You're building a custom website integration

### Creating an API Key

1. Go to **Settings** > **API Keys**
2. Click **"Create API Key"**
3. Give the key a name (e.g., "Website Integration" or "CRM Connection")
4. Choose the permissions for this key:
   - **Read only** - Can view data but not change anything
   - **Read and write** - Can view and modify data
5. Click **"Create"**
6. **Copy the key immediately** - You won't be able to see it again after you leave the page

### Best Practices for API Keys

- **Name keys clearly** - So you know what each one is used for
- **Use read-only when possible** - Only give write access if absolutely necessary
- **Rotate keys regularly** - Create new keys and delete old ones every few months
- **Never share keys publicly** - Don't put them in emails, chat messages, or code repositories
- **Delete unused keys** - If an integration is no longer active, delete its key

### Revoking an API Key

If a key is compromised or no longer needed:

1. Go to **Settings** > **API Keys**
2. Find the key you want to revoke
3. Click the three dots next to it
4. Click **"Revoke"**
5. Confirm the revocation

> **Warning:** Revoking a key immediately breaks any integration using it. Make sure you know what systems are using the key before revoking it.

---

## Common Team Scenarios

### Scenario 1: Small Business Owner + Receptionist

**Owner:** Business owner
**Viewer:** Receptionist (to monitor conversations and see how the agent is performing)

The owner sets up and manages the agent. The receptionist can view chat history to see what customers are asking and provide feedback on the agent's responses.

### Scenario 2: Restaurant + Web Developer

**Owner:** Restaurant owner
**Admin:** Restaurant manager
**Developer:** Web developer

The owner manages the account. The manager handles day-to-day agent improvements (updating menus, adding playbooks). The developer embeds the widget and sets up payment integrations.

### Scenario 3: Marketing Agency + Client

**Owner:** Agency account
**Admin:** Agency account manager
**Developer:** Agency developer
**Viewer:** Client

The agency manages everything. The client can view performance and chat history to see how the agent is working for their business.

### Scenario 4: Clinic with Multiple Staff

**Owner:** Clinic owner
**Admin:** Office manager
**Developer:** IT contractor
**Viewers:** Receptionists and practitioners

The owner oversees everything. The office manager handles daily operations. The IT contractor sets up integrations with the clinic's booking system. Staff members can view conversations to understand what patients are asking.

---

## Transferring Ownership

If you need to transfer ownership to another team member:

1. Go to **Settings** > **Team**
2. Find the team member you want to make the new owner
3. Click the three dots next to their name
4. Click **"Transfer Ownership"**
5. Confirm the transfer

> **Warning:** After transferring ownership, you will become an Admin. The new owner will have full control over the account, including billing and team management.

---

## Removing Team Members

When someone leaves your team or no longer needs access:

1. Go to **Settings** > **Team**
2. Find the team member
3. Click the three dots next to their name
4. Click **"Remove"**
5. Confirm the removal

**What happens when someone is removed:**
- They lose access to your account immediately
- Any API keys they created remain active (review and revoke if needed)
- Their name is removed from the team list
- They cannot rejoin without a new invitation

---

## Security Best Practices

### 1. Use the Principle of Least Privilege

Give people only the access they need. If someone only needs to view conversations, give them Viewer access, not Admin.

### 2. Review Team Access Regularly

Every few months, review your team list and remove anyone who no longer needs access.

### 3. Monitor API Key Usage

Check which API keys are active and what they're being used for. Revoke any you don't recognize.

### 4. Use Strong Passwords

Make sure everyone on your team uses strong, unique passwords for their accounts.

### 5. Enable Two-Factor Authentication

If available, enable two-factor authentication for an extra layer of security.

### 6. Be Careful with Developer Access

Developers can connect tools and integrations. Make sure you trust anyone with Developer access, as they can connect systems that handle customer data and payments.

---

## What's Next?

Now that your team is set up:
- **Billing** - Understand your plan limits and usage
- **Compliance** - Make sure your team follows privacy regulations
- **Playbooks** - Collaborate with your team to create effective conversation flows
