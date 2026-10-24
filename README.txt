Training HQ — Week Review, Rest Display & Projected Max Update

This package builds on the latest Training HQ version with screenshot day import, multi-program support, optional/custom progression engines, PWA launch fix, and rest/duration timers.

Changes in this update:
- The rest timer panel is shown in workout logging only when a rest interval is configured for that exercise. A programmed rest still starts automatically when a set is marked complete.
- Repetition inputs are shown only when reps are specified for an exercise. For a timed exercise, leave the Reps / duration field blank and enter a duration per set; the logger then omits the reps input and records completion without inventing a rep count.
- The Today page includes a week selector to view the planned schedule for any of the 12 weeks, alongside a comparison of logged weighted performance for the selected day versus the previous week.
- Recent activity is collapsible and starts minimised.
- Lifter profile settings let users save bodyweight and age locally.
- Projected one-rep max calculator estimates a 1RM from a recent set using an average of five formula estimates (Epley, Brzycki, Lander, Lombardi and Mayhew), and displays the estimated lift-to-bodyweight ratio when bodyweight is entered. This is a training estimate, not a tested max. Age is stored for context but is not used to adjust the estimate.

Deploy all files to the existing Cloudflare Worker, not a new Worker. Export a JSON backup before deploying. Keep the existing Worker URL and Google OAuth configuration. The service-worker cache version is incremented so the new files can replace the old cached app.

Projected 1RM notes:
- Most reliable for sets of roughly 1–10 reps performed close to failure; estimates become less reliable at higher reps.
- The calculation estimates the maximum for the selected lift. It does not assign a Strength Level category because those categories depend on exercise-specific reference standards and profile assumptions.
- Strength Level's own calculator describes 1RM as an estimate and notes that age is not applied to its current standards. See https://strengthlevel.com/.


UPDATE: Flexible reference maximums
Training settings now lets you add, rename, and remove any exercise reference max. Saving reference maximums automatically adds each lift name to the Exercise Library. Exact exercise-name matches can be used for percentage-based prescriptions.
