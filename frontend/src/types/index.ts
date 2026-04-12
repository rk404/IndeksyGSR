export interface SearchResult {
  qdrant_id: number | string | null;
  indeks: string;
  nazwa: string;
  komb_id: string;
  jdmr_nazwa: string;
  score: number;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
}

export interface ScrapedData {
  title: string;
  price: string;
  specifications: Record<string, string>;
  description: string;
}

export interface SearchUrlResponse {
  scraped: ScrapedData;
  query: string;
  results: SearchResult[];
}

export interface GenerateDescriptionResponse {
  description: string;
  error: boolean;
}

export interface SegmentTree {
  pos1: Record<string, string>;
  pos1_kod: Record<string, string>;
  pos2_by_parent: Record<string, [number, string][]>;
  pos3_by_parent: Record<string, [number, string][]>;
  pos2_kod: Record<string, string>;
  pos3_kod: Record<string, string>;
  pos4_values: string[];
  pos5_values: string[];
  pos6_values: string[];
}

export interface SegmentProposal {
  seg1_slit_id: number;
  seg1_text: string;
  seg2_slit_id: number;
  seg2_text: string;
  seg3_slit_id: number;
  seg3_text: string;
  score: number;
}

export interface BulkResultRow {
  opis_materialu: string;
  indeks: string;
  nazwa: string;
  score: number;
}

export interface BulkSearchResponse {
  results: BulkResultRow[];
  total: number;
}

export interface ProposalItem {
  id: string;
  query: string;
  indeks: string;
  nazwa: string;
  seg1: string;
  seg2: string;
  seg3: string;
  seg4: string;
  seg5: string;
  seg6: string;
  status: string;
  proposed_at: string;
}
