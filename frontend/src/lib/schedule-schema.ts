import { z } from 'zod'

const cronPattern = /^(\S+\s+){4}\S+$/

export const scheduleSchema = z.object({
  enabled: z.boolean(),
  cron: z
    .string()
    .trim()
    .regex(cronPattern, 'Use a five-part cron expression.'),
  timezone: z.string().trim().min(1, 'Timezone is required.'),
  deliveryWindow: z.string().trim().min(1, 'Delivery window is required.'),
  includeWeekends: z.boolean(),
})

export type ScheduleFormValues = z.infer<typeof scheduleSchema>
