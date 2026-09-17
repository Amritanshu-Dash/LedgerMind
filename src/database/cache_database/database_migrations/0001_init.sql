--
-- PostgreSQL database dump
--

\restrict 6uBMIjtmxiLy00h6fPOHIyZrbRFb0SDgta1qPTwbSobaV5g0ed0Dr8GgFoQmGKb

-- Dumped from database version 17.6
-- Dumped by pg_dump version 17.6

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: handle_cache_data_update(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.handle_cache_data_update() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = now();
    IF NEW.reviewed_by IS DISTINCT FROM OLD.reviewed_by THEN
        NEW.reviewed_at = now();
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: prevent_delete_unless_rejected(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.prevent_delete_unless_rejected() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF OLD.data_review_status <> 'rejected' THEN
        RAISE EXCEPTION 'Cannot delete row %: data_review_status is ''%'', must be ''rejected''.',
            OLD.id, OLD.data_review_status;
    END IF;
    RETURN OLD;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: cache_data; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cache_data (
    id bigint NOT NULL,
    company_name character varying(150) NOT NULL,
    company_stock_name character varying(50) NOT NULL,
    extracted_data jsonb NOT NULL,
    file_path text NOT NULL,
    original_filename text NOT NULL,
    data_review_status character varying(20) DEFAULT 'system-ingested'::character varying NOT NULL,
    reviewed_by character varying(100),
    reviewed_at timestamp with time zone,
    main_db_status character varying(20) DEFAULT NULL::character varying,
    main_db_requested_at timestamp with time zone,
    main_db_resolved_at timestamp with time zone,
    comments text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    unique_query_id bigint NOT NULL,
    CONSTRAINT cache_data_data_review_status_check CHECK (((data_review_status)::text = ANY ((ARRAY['system-ingested'::character varying, 'in_progress'::character varying, 'approved'::character varying, 'rejected'::character varying])::text[]))),
    CONSTRAINT cache_data_main_db_status_check CHECK ((((main_db_status)::text = ANY ((ARRAY['requested'::character varying, 'accepted'::character varying, 'rejected'::character varying])::text[])) OR (main_db_status IS NULL))),
    CONSTRAINT main_db_status_only_when_approved CHECK (((main_db_status IS NULL) OR ((data_review_status)::text = 'approved'::text))),
    CONSTRAINT reviewer_required_when_reviewed CHECK ((((data_review_status)::text = 'system-ingested'::text) OR ((reviewed_by IS NOT NULL) AND (btrim((reviewed_by)::text) <> ''::text))))
);


--
-- Name: cache_data_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cache_data_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cache_data_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cache_data_id_seq OWNED BY public.cache_data.id;


--
-- Name: cache_queries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cache_queries (
    unique_query_id bigint NOT NULL,
    original_query text NOT NULL,
    system_converted_query text NOT NULL,
    query_sense text NOT NULL,
    attachment_count integer DEFAULT 0 NOT NULL,
    attachment_summary text DEFAULT '0 attachments'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT cache_queries_attachment_count_check CHECK ((attachment_count >= 0))
);


--
-- Name: cache_queries_unique_query_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cache_queries_unique_query_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cache_queries_unique_query_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cache_queries_unique_query_id_seq OWNED BY public.cache_queries.unique_query_id;


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version text NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: cache_data id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cache_data ALTER COLUMN id SET DEFAULT nextval('public.cache_data_id_seq'::regclass);


--
-- Name: cache_queries unique_query_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cache_queries ALTER COLUMN unique_query_id SET DEFAULT nextval('public.cache_queries_unique_query_id_seq'::regclass);


--
-- Name: cache_data cache_data_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cache_data
    ADD CONSTRAINT cache_data_pkey PRIMARY KEY (id);


--
-- Name: cache_queries cache_queries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cache_queries
    ADD CONSTRAINT cache_queries_pkey PRIMARY KEY (unique_query_id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: idx_cache_company_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cache_company_status ON public.cache_data USING btree (company_name, data_review_status);


--
-- Name: idx_cache_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cache_created_at ON public.cache_data USING btree (created_at);


--
-- Name: idx_cache_data_review_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cache_data_review_status ON public.cache_data USING btree (data_review_status);


--
-- Name: idx_cache_data_unique_query_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cache_data_unique_query_id ON public.cache_data USING btree (unique_query_id);


--
-- Name: idx_cache_main_db_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cache_main_db_status ON public.cache_data USING btree (main_db_status);


--
-- Name: idx_cache_queries_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cache_queries_created_at ON public.cache_queries USING btree (created_at);


--
-- Name: cache_data cache_data_before_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER cache_data_before_update BEFORE UPDATE ON public.cache_data FOR EACH ROW EXECUTE FUNCTION public.handle_cache_data_update();


--
-- Name: cache_data enforce_delete_only_when_rejected; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER enforce_delete_only_when_rejected BEFORE DELETE ON public.cache_data FOR EACH ROW EXECUTE FUNCTION public.prevent_delete_unless_rejected();


--
-- Name: cache_data cache_data_unique_query_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cache_data
    ADD CONSTRAINT cache_data_unique_query_id_fkey FOREIGN KEY (unique_query_id) REFERENCES public.cache_queries(unique_query_id) ON DELETE SET NULL;


--
-- PostgreSQL database dump complete
--

\unrestrict 6uBMIjtmxiLy00h6fPOHIyZrbRFb0SDgta1qPTwbSobaV5g0ed0Dr8GgFoQmGKb

