# WarungWise — Project Brief and Scope

**Project title:** WarungWise  
**Tagline:** *Smarter Stock. Less Waste. Better Decisions.*  
**Document status:** Living project brief, updated after implementation  
**Implementation status:** Core workflows and reports are implemented. GitHub Actions currently reports 64 passing automated tests; manual browser, security, and submission checks remain.

## 1. Executive Summary

WarungWise is a proposed web application for inventory, batch expiry, and restock management in small Indonesian neighborhood grocery shops (warungs). It aims to help shop owners and staff maintain product records, track stock movements, monitor expiry dates at batch level, record sales and losses, and make more informed restocking decisions.

The application will use Python, Flask, SQLite, HTML, CSS, JavaScript, Bootstrap, and Jinja. Its core workflows will run locally and will not require paid external APIs, paid AI services, payment integrations, or a cloud subscription. Synthetic demonstration data may be included, clearly identified as sample data rather than evidence of real-world business validation.

WarungWise is intended to do more than display stock totals. Its central value is to connect inventory records and transaction history to practical operational information, while making calculations and limitations understandable to the user.

## 2. Problem Statement

Small shops may manage inventory through handwritten notes, memory, or disconnected records. These approaches can make it difficult to know which products are running low, distinguish batches with different expiry dates, review sales history, or estimate how much stock should be replenished. They can also make it difficult to trace why inventory changed or to understand the recorded cost of goods that were damaged or expired.

WarungWise will provide a structured, locally stored record of products, stock batches, sales, and stock movements. It will use these records to highlight inventory that needs attention and to provide transparent, rule-based restock recommendations. The project will not claim that the application reduces losses or improves real business outcomes unless those outcomes are evaluated with appropriate evidence.

## 3. Target Users and Use Context

The primary users are:

- Owners of small neighborhood grocery shops and warungs.
- Shop managers responsible for receiving stock and recording sales.
- Staff who monitor expiry dates and record damaged or expired goods.

For the initial version, the application will assume one shop and one local user. The interface will use Indonesian, monetary values will be represented in Indonesian rupiah (IDR), and the application will be designed for use on a laptop or mobile browser. Authentication, multi-user permissions, and multi-branch synchronization are outside the initial scope.

## 4. Project Objectives

WarungWise aims to:

1. Provide product management features to create, view, edit, search, and archive product records.
2. Track inventory by batch so that one product can have multiple quantities and expiry dates.
3. Record stock receipts, sales, adjustments, and disposal of damaged or expired goods.
4. Preserve an auditable history of stock movements and prevent sales from creating negative sellable inventory.
5. Identify low stock, approaching expiry, and expired batches using clear status labels.
6. Calculate sales summaries and recorded losses from database records rather than hard-coded dashboard values.
7. Provide transparent restock recommendations based on recorded sales and configurable assumptions.
8. Deliver a local application that can be run, tested, documented, and explained by its developer.

## 5. Scope: MVP, Final Target, and Exclusions

### 5.1 MVP — Core Functional Foundation

The Minimum Viable Product (MVP) will establish the inventory workflows before reports and additional features are built. It must include:

- Product creation, listing, editing, searching, validation, and archiving.
- Stock intake recorded as a batch, with a receipt date and an optional expiry date.
- Sales recording that reduces stock in a controlled and traceable way.
- Stock adjustments and records for damaged or expired goods that are removed from sellable inventory.
- Stock movement history showing the movement type, quantity, timestamp, and relevant product or batch.
- Batch-level expiry status and low-stock indicators.
- Server-side validation and database transactions that prevent invalid or partial stock updates.

**MVP completion gate:** A user must be able to create a product, receive stock into a batch, record a valid sale, and verify that both the stock balance and movement history are updated correctly. Invalid sales must be rejected without changing inventory.

### 5.2 Target Features for the Final Version

After the MVP is stable and tested, the project will target:

- A dashboard with active product counts, low-stock alerts, upcoming expiry, expired batches, and transaction summaries.
- Rule-based restock recommendations using average daily sales, replenishment lead time, safety stock, and sellable inventory.
- Sales reports and reports of goods recorded as damaged or expired.
- Date filters and CSV export.
- Responsive layouts, accessible labels, readable status text, informative empty states, clear success and error messages, and confirmations for important actions.
- Automated tests for core business rules, documented setup instructions, and a comprehensive project README.

Features will be included only when they can be implemented, tested, and explained reliably. The final feature list may be narrowed if necessary to protect the correctness of the core workflows.

### 5.3 Explicitly Out of Scope for Version One

The initial version will not include user accounts, role-based access control, multiple shops or branches, cloud synchronization, supplier or marketplace integrations, payment processing, a native mobile application, barcode-scanning hardware, or machine-learning-based forecasting.

These exclusions keep the project focused on inventory correctness and transparent business logic. They may be reconsidered only after the core application works reliably and a clear requirement justifies the added complexity.

## 6. Technology Stack and Rationale

- **Python:** implements validation and business rules.
- **Flask:** provides lightweight web routing and request handling.
- **SQLite:** stores products, batches, and transaction records locally without requiring a separate database server.
- **HTML5 and Jinja:** define page structure and render database-backed information.
- **CSS3 and Bootstrap:** provide consistent styling and responsive layouts.
- **JavaScript:** supports small interface interactions where needed, without moving authoritative inventory validation away from the server.
- **Python standard library:** will be preferred for CSV export and general data processing where sufficient.

No paid API or AI service is required. Additional dependencies will be introduced only where they provide a specific benefit, and all actual dependencies will be documented accurately.

## 7. Initial Business Rules and Assumptions

### 7.1 Batch-Level Inventory

A product may have multiple batches with different receipt dates and expiry dates. Sellable inventory must be derived from the remaining quantities of its eligible batches. A single aggregate product quantity must not replace the batch records or their history.

### 7.2 Expiry and FEFO

For products with expiry dates, sales will follow **First Expired, First Out (FEFO)**: eligible batches with the earliest expiry date are used first. Receipt date will act as a tie-breaker where necessary. Expired or otherwise ineligible batches must not satisfy a sale. Products without an expiry date may be supported, but the application must represent their expiry status as unknown or not applicable rather than inventing a date.

### 7.3 Atomic Stock Transactions

A stock change and its corresponding movement record must succeed together or be rolled back together. Database constraints, server-side validation, and transaction handling will be used to prevent negative quantities and inconsistent records. Repeated form submissions and failed database operations must be considered during implementation and testing.

### 7.4 Revenue, Profit, and Recorded Loss

Revenue is not the same as profit. Sales revenue will be calculated from recorded sales. Gross profit estimates must account for the relevant cost basis of goods sold. The value of damaged or expired goods removed from inventory will be calculated from the quantity recorded as disposed of and its applicable cost basis. An expiry warning alone is not a realized loss.

### 7.5 Restock Recommendation

The initial rule-based calculation is:

    target_stock = (average_daily_sales * lead_time_days) + safety_stock
    suggested_restock = max(0, target_stock - sellable_stock)

The application will explain the inputs and assumptions behind each recommendation. Recommendations are estimates, not guarantees. If sales history is insufficient, the interface must disclose that limitation and avoid presenting an unsupported estimate as reliable. The first version will not subtract unreceived purchase orders because purchase-order tracking is not included in scope.

## 8. Measurable Acceptance Criteria

The final application will be assessed against the following observable outcomes:

1. Products can be created, edited, searched, and archived without erasing historical movements.
2. Receiving stock creates or updates the intended batch and records the corresponding movement.
3. A valid sale reduces eligible batch quantities and creates a sales movement.
4. A sale exceeding available sellable inventory is rejected, with no partial stock change.
5. Batch expiry statuses are calculated from batch-level dates and a defined warning window.
6. Expired batches are excluded from sellable inventory and can be recorded as disposed of through a traceable operation.
7. Recorded loss calculations use disposed quantities and the documented cost basis.
8. Restock recommendations follow the defined formula and handle insufficient sales history, zero stock, and sufficient stock.
9. Dashboard totals, date-filtered reports, and CSV exports agree with the underlying database records.
10. Invalid or missing form values produce understandable feedback and do not corrupt stored data.
11. The application can be initialized and run locally using the documented instructions without a paid external service.
12. Automated and manual test results are recorded honestly; no feature or test is described as complete until it has actually been verified.

These are planned acceptance criteria. They are not claims that the application has already been implemented or that any tests have passed.

## 9. Why the Project Is Substantive

WarungWise involves more than basic create, read, update, and delete operations. Its main technical challenges include modeling one-to-many relationships between products and batches, preserving an auditable movement history, applying FEFO to sales, updating inventory atomically, validating business constraints, and producing correct reports from related records.

It also requires practical interface design, transparent calculations, automated tests, and documentation. These elements provide opportunities to apply Python, SQL, algorithms, web programming, and software testing to a specific operational problem. The goal is not to maximize the number of features, but to deliver a coherent application whose behavior can be demonstrated and explained.

## 10. Implementation Roadmap

1. **Project Proposal and Scope:** finalize the problem statement, MVP, exclusions, risks, and acceptance criteria.
2. **Requirements and User Flows:** define inputs, expected outcomes, validation rules, and failure cases for each workflow.
3. **Database Design:** specify tables, relationships, constraints, indexing where justified, and transaction boundaries.
4. **Backend Foundation:** establish Flask configuration, SQLite access, base templates, and error handling.
5. **Product Management:** implement product CRUD, search, validation, and archiving.
6. **Stock Intake and Batch Tracking:** implement receiving, batch quantities, receipt dates, and expiry dates.
7. **Sales and Stock Movements:** implement FEFO, stock adjustments, disposal, audit history, and atomic transactions.
8. **Dashboard and Expiry Alerts:** derive key summaries and alerts from stored records.
9. **Restock Recommendations:** implement the documented calculation and test boundary cases.
10. **Reports and CSV Export:** add date filters, summaries, and verified CSV output.
11. **Interface Polish:** improve responsiveness, accessibility, empty states, and user feedback.
12. **Testing and Security Review:** execute automated and manual tests and address discovered defects.
13. **Documentation and Demo:** document the actual implementation and prepare a project demonstration of no more than three minutes.
14. **Submission Review:** follow the official CS50x 2026 instructions, submit the project, and verify its status in the course Gradebook.

Each milestone must have a review gate. Work should not proceed on the assumption that a stage succeeded until its acceptance checks have been performed.

## 11. Key Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Scope becomes too large | Complete and test the MVP before adding enhancements. |
| Inventory and movement history disagree | Use database transactions and a single, documented stock model. |
| Restock advice is misleading | Show the formula, assumptions, and limits of available data. |
| Local records are accidentally lost | Document database initialization and backup procedures; never silently replace an existing database. |
| Tests or business impact are overstated | Report observed results only and label synthetic data clearly. |
| Secrets or sensitive data enter the repository | Exclude credentials, tokens, and private business data from source control. |

## 12. Academic Integrity and AI-Assistance Transparency

The official CS50x 2026 Final Project specification is the primary reference for project expectations and submission requirements: https://cs50.harvard.edu/x/project/.

CS50x permits the use of external AI tools for the final project, but the essence of the work must remain the student's own, and use of such tools must be cited in relevant code comments as required by the official specification. This planning document was prepared with ChatGPT assistance based on the project requirements supplied by the student. The student must review, adapt, and understand the design decisions and implementation. Any code comments describing AI assistance must accurately reflect the assistance actually used for that specific code.

No user research, field validation, test result, or business outcome is claimed at this planning stage.
