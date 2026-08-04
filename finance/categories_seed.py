"""The household's starting category tree.

Two levels deep on purpose. The classifier is markedly more consistent
choosing from a short, clearly-described list than from a sprawling taxonomy,
and a category nobody ever filters by is just noise in a dropdown.

`description` is not decoration — it is fed to the classifier as the
definition of the category, so it should say what belongs and, where the
boundary is genuinely unclear, what does not.

A few slugs are load-bearing and referenced in code (see SYSTEM_SLUGS).
"""

UNCATEGORIZED_SLUG = "uncategorized"
TRANSFER_SLUG = "transfer-internal"
CARD_PAYMENT_SLUG = "transfer-card-payment"

SYSTEM_SLUGS = frozenset({UNCATEGORIZED_SLUG, TRANSFER_SLUG, CARD_PAYMENT_SLUG})

CATEGORY_TREE = [
    {
        "name": "Income",
        "slug": "income",
        "kind": "income",
        "children": [
            {"name": "Salary", "slug": "income-salary", "description": "Regular paycheck deposits from an employer."},
            {"name": "Bonus & Commission", "slug": "income-bonus", "description": "Irregular employment income."},
            {"name": "Interest", "slug": "income-interest", "description": "Interest paid on deposit accounts."},
            {"name": "Dividends & Capital Gains", "slug": "income-investment", "description": "Investment distributions."},
            {"name": "Reimbursement", "slug": "income-reimbursement", "description": "Money paid back to us — expenses, refunds, insurance claims."},
            {"name": "Gifts Received", "slug": "income-gifts", "description": "Cash gifts received."},
            {"name": "Other Income", "slug": "income-other", "description": "Income that fits nowhere else."},
        ],
    },
    {
        "name": "Housing",
        "slug": "housing",
        "children": [
            {"name": "Mortgage Payment", "slug": "housing-mortgage", "description": "Principal, interest, and escrow to the mortgage servicer."},
            {"name": "Property Tax", "slug": "housing-property-tax", "description": "Property tax paid directly rather than through escrow."},
            {"name": "Home Insurance", "slug": "housing-insurance", "description": "Homeowner's insurance premiums."},
            {"name": "Utilities", "slug": "housing-utilities", "description": "Electric, gas, water, sewer, trash."},
            {"name": "Internet & Phone", "slug": "housing-internet-phone", "description": "Broadband and mobile service."},
            {"name": "Home Maintenance", "slug": "housing-maintenance", "description": "Repairs, lawn care, cleaning, pest control."},
            {"name": "Home Improvement", "slug": "housing-improvement", "description": "Projects and durable upgrades, not routine repairs."},
            {"name": "Furnishings", "slug": "housing-furnishings", "description": "Furniture, appliances, decor, household goods."},
        ],
    },
    {
        "name": "Transportation",
        "slug": "transportation",
        "children": [
            {"name": "Fuel", "slug": "transport-fuel", "description": "Gas stations and EV charging."},
            {"name": "Auto Loan", "slug": "transport-auto-loan", "description": "Car loan or lease payments."},
            {"name": "Auto Insurance", "slug": "transport-auto-insurance", "description": "Vehicle insurance premiums."},
            {"name": "Auto Maintenance", "slug": "transport-maintenance", "description": "Service, repairs, tires, car washes."},
            {"name": "Parking & Tolls", "slug": "transport-parking-tolls", "description": "Parking, tolls, vehicle registration."},
            {"name": "Rideshare & Taxi", "slug": "transport-rideshare", "description": "Uber, Lyft, taxis."},
            {"name": "Public Transit", "slug": "transport-transit", "description": "Trains, buses, transit passes."},
        ],
    },
    {
        "name": "Food",
        "slug": "food",
        "children": [
            {"name": "Groceries", "slug": "food-groceries", "description": "Supermarkets and food shopping to cook at home."},
            {"name": "Restaurants", "slug": "food-restaurants", "description": "Sit-down and counter-service meals out."},
            {"name": "Coffee & Snacks", "slug": "food-coffee", "description": "Coffee shops and small food purchases."},
            {"name": "Delivery & Takeout", "slug": "food-delivery", "description": "DoorDash, Uber Eats, pickup orders."},
            {"name": "Alcohol & Bars", "slug": "food-alcohol", "description": "Bars, liquor stores, wine."},
        ],
    },
    {
        "name": "Health",
        "slug": "health",
        "children": [
            {"name": "Health Insurance", "slug": "health-insurance", "description": "Medical, dental, and vision premiums paid directly."},
            {"name": "Medical", "slug": "health-medical", "description": "Doctor visits, hospital bills, lab work, copays."},
            {"name": "Dental & Vision", "slug": "health-dental-vision", "description": "Dentist, orthodontist, optometrist, glasses."},
            {"name": "Pharmacy", "slug": "health-pharmacy", "description": "Prescriptions and drugstore health purchases."},
            {"name": "Fitness", "slug": "health-fitness", "description": "Gym memberships, classes, fitness apps."},
            {"name": "Therapy & Wellness", "slug": "health-therapy", "description": "Mental health care and wellness services."},
        ],
    },
    {
        "name": "Personal",
        "slug": "personal",
        "children": [
            {"name": "Clothing", "slug": "personal-clothing", "description": "Clothes, shoes, accessories."},
            {"name": "Personal Care", "slug": "personal-care", "description": "Haircuts, salon, toiletries, cosmetics."},
            {"name": "Subscriptions", "slug": "personal-subscriptions", "description": "Recurring software, news, and membership charges."},
            {"name": "Hobbies", "slug": "personal-hobbies", "description": "Hobby supplies, sports, crafts, games."},
            {"name": "Books & Education", "slug": "personal-education", "description": "Books, courses, tuition, professional development."},
            {"name": "Gifts Given", "slug": "personal-gifts", "description": "Presents and charitable giving."},
        ],
    },
    {
        "name": "Entertainment",
        "slug": "entertainment",
        "children": [
            {"name": "Streaming", "slug": "entertainment-streaming", "description": "Netflix, Spotify, and similar media subscriptions."},
            {"name": "Events & Outings", "slug": "entertainment-events", "description": "Cinema, concerts, sports, museums."},
            {"name": "Travel", "slug": "entertainment-travel", "description": "Flights, trains, rental cars for trips."},
            {"name": "Lodging", "slug": "entertainment-lodging", "description": "Hotels and short-term rentals."},
        ],
    },
    {
        "name": "Financial",
        "slug": "financial",
        "children": [
            {"name": "Student Loan Payment", "slug": "financial-student-loan", "description": "Payments to student loan servicers."},
            {"name": "Life Insurance", "slug": "financial-life-insurance", "description": "Term and permanent life insurance premiums."},
            {"name": "Retirement Contribution", "slug": "financial-retirement", "description": "Contributions to retirement accounts outside payroll."},
            {"name": "Investment Contribution", "slug": "financial-investment", "description": "Money moved into brokerage accounts."},
            {"name": "Bank Fees", "slug": "financial-fees", "description": "Account fees, overdrafts, ATM and foreign transaction fees."},
            {"name": "Interest Charges", "slug": "financial-interest", "description": "Credit card and loan interest charged to us."},
            {"name": "Taxes", "slug": "financial-taxes", "description": "Tax payments made directly, not payroll withholding."},
            {"name": "Professional Services", "slug": "financial-professional", "description": "Accountants, lawyers, financial advisors."},
        ],
    },
    {
        "name": "Pets",
        "slug": "pets",
        "children": [
            {"name": "Pet Food & Supplies", "slug": "pets-supplies", "description": "Food, litter, toys, equipment."},
            {"name": "Veterinary", "slug": "pets-vet", "description": "Vet visits, medication, pet insurance."},
            {"name": "Pet Services", "slug": "pets-services", "description": "Grooming, boarding, walking, training."},
        ],
    },
    {
        "name": "Shopping",
        "slug": "shopping",
        "children": [
            {"name": "General Merchandise", "slug": "shopping-general", "description": "Amazon, Target, and other mixed-basket retailers where the contents are unclear."},
            {"name": "Electronics", "slug": "shopping-electronics", "description": "Devices, computers, accessories."},
            {"name": "Household Supplies", "slug": "shopping-household", "description": "Cleaning products, paper goods, consumables."},
        ],
    },
    {
        "name": "Transfers",
        "slug": "transfers",
        "kind": "transfer",
        "children": [
            {"name": "Internal Transfer", "slug": TRANSFER_SLUG, "kind": "transfer", "system": True, "description": "Money moved between our own accounts. Never spend or income."},
            {"name": "Credit Card Payment", "slug": CARD_PAYMENT_SLUG, "kind": "transfer", "system": True, "description": "Paying a credit card from a bank account."},
        ],
    },
    {
        "name": "Uncategorized",
        "slug": UNCATEGORIZED_SLUG,
        "system": True,
        "description": "Not yet classified, or genuinely unclassifiable.",
    },
]
