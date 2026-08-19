# efps-automations

AWS automation modules for EasyFind Property Solutions.

Each module is a self-contained automation — its own Lambda, IAM roles,
configs, and documentation. Nothing is shared between modules unless explicitly
placed in `shared/`.

---

## Modules

| Module | Description | Status |
|--------|-------------|--------|
| [spend-guard](./modules/spend-guard/README.md) | Stops EC2, RDS, and throttles Lambda when daily AWS spend exceeds $5 | Active |

---

## Naming Convention

All AWS resources follow the pattern: `efps-{module}-{resource-type}`

Full standard is documented in `.kiro/steering/efps-naming-standard.md`.

---

## Secrets

- Secrets are stored in AWS Secrets Manager
- Path convention: `efps/{module}/{secret-name}`
- Each module's IAM role only has access to its own secrets (`efps/{module}/*`)
- Never commit `.env` files — only `.env.example` with key names

---

## Repository Structure

```
efps-automations/
├── modules/
│   └── spend-guard/        # Module 01 — cost protection
├── shared/                 # Shared utilities (currently empty)
├── .gitignore
└── README.md
```

---

## Adding a New Module

1. Create `modules/{module-name}/` folder
2. Follow the file structure from an existing module
3. Add a `README.md` covering the module A to Z
4. Register the module in the table above
5. Register it in `.kiro/steering/efps-naming-standard.md` Modules Registry
