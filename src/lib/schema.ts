import { z } from 'zod';

export const ClientDataSchema = z.object({
  slug: z.string(),
  business: z.object({
    name: z.string(),
    tagline: z.string(),
    description: z.string(),
    neighborhood: z.string(),
    city: z.string(),
    address: z.string(),
    mapsUrl: z.string(),
    whatsapp: z.string(),
    whatsappMessage: z.string(),
    instagram: z.string(),
    hours: z.string(),
  }),
  branding: z.object({
    primaryColor: z.string(),
    accentColor: z.string(),
    logo: z.string(),
    heroImage: z.string(),
  }),
  services: z.array(
    z.object({
      name: z.string(),
      priceFrom: z.string(),
      description: z.string(),
    }),
  ),
  gallery: z.array(
    z.object({
      before: z.string(),
      after: z.string(),
      caption: z.string(),
    }),
  ),
  trust: z.object({
    googleRating: z.string(),
    googleReviewCount: z.number(),
    googleReviewUrl: z.string(),
    yearsInBusiness: z.number(),
    ownerName: z.string(),
  }),
  legal: z.object({
    privacyPolicyUrl: z.string(),
    cnpj: z.string().nullable(),
  }),
  tracking: z.object({
    whatsappEndpoint: z.string(),
  }),
});

export type ClientData = z.infer<typeof ClientDataSchema>;
