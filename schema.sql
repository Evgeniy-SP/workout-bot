--
-- PostgreSQL database dump
--

\restrict FpWc5M8dcXkpMPRUfslrUjwEQPuQipxV0xXKEKSDJBhH8ybS8xBFWaeOAc8YAGw

-- Dumped from database version 16.15
-- Dumped by pg_dump version 16.15

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: exercises; Type: TABLE; Schema: public; Owner: bot_user
--

CREATE TABLE public.exercises (
    id integer NOT NULL,
    workout_type_id integer NOT NULL,
    name character varying(128) NOT NULL,
    kind character varying(16) NOT NULL,
    sets integer,
    reps integer,
    weight_kg double precision,
    duration_seconds integer,
    is_optional boolean NOT NULL,
    notes text,
    sort_order integer NOT NULL,
    is_archived boolean DEFAULT false NOT NULL
);


ALTER TABLE public.exercises OWNER TO bot_user;

--
-- Name: exercises_id_seq; Type: SEQUENCE; Schema: public; Owner: bot_user
--

CREATE SEQUENCE public.exercises_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.exercises_id_seq OWNER TO bot_user;

--
-- Name: exercises_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: bot_user
--

ALTER SEQUENCE public.exercises_id_seq OWNED BY public.exercises.id;


--
-- Name: session_sets; Type: TABLE; Schema: public; Owner: bot_user
--

CREATE TABLE public.session_sets (
    id integer NOT NULL,
    session_id integer NOT NULL,
    exercise_id integer NOT NULL,
    set_number integer NOT NULL,
    reps integer,
    weight_kg double precision,
    duration_seconds integer,
    completed boolean NOT NULL
);


ALTER TABLE public.session_sets OWNER TO bot_user;

--
-- Name: session_sets_id_seq; Type: SEQUENCE; Schema: public; Owner: bot_user
--

CREATE SEQUENCE public.session_sets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.session_sets_id_seq OWNER TO bot_user;

--
-- Name: session_sets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: bot_user
--

ALTER SEQUENCE public.session_sets_id_seq OWNED BY public.session_sets.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: bot_user
--

CREATE TABLE public.users (
    id integer NOT NULL,
    tg_id bigint NOT NULL,
    username character varying(64),
    full_name character varying(128) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.users OWNER TO bot_user;

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: bot_user
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.users_id_seq OWNER TO bot_user;

--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: bot_user
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: workout_sessions; Type: TABLE; Schema: public; Owner: bot_user
--

CREATE TABLE public.workout_sessions (
    id integer NOT NULL,
    user_id integer NOT NULL,
    workout_type_id integer NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone
);


ALTER TABLE public.workout_sessions OWNER TO bot_user;

--
-- Name: workout_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: bot_user
--

CREATE SEQUENCE public.workout_sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.workout_sessions_id_seq OWNER TO bot_user;

--
-- Name: workout_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: bot_user
--

ALTER SEQUENCE public.workout_sessions_id_seq OWNED BY public.workout_sessions.id;


--
-- Name: workout_types; Type: TABLE; Schema: public; Owner: bot_user
--

CREATE TABLE public.workout_types (
    id integer NOT NULL,
    user_id integer NOT NULL,
    name character varying(64) NOT NULL,
    description text,
    sort_order integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    is_archived boolean DEFAULT false NOT NULL
);


ALTER TABLE public.workout_types OWNER TO bot_user;

--
-- Name: workout_types_id_seq; Type: SEQUENCE; Schema: public; Owner: bot_user
--

CREATE SEQUENCE public.workout_types_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.workout_types_id_seq OWNER TO bot_user;

--
-- Name: workout_types_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: bot_user
--

ALTER SEQUENCE public.workout_types_id_seq OWNED BY public.workout_types.id;


--
-- Name: exercises id; Type: DEFAULT; Schema: public; Owner: bot_user
--

ALTER TABLE ONLY public.exercises ALTER COLUMN id SET DEFAULT nextval('public.exercises_id_seq'::regclass);


--
-- Name: session_sets id; Type: DEFAULT; Schema: public; Owner: bot_user
--

ALTER TABLE ONLY public.session_sets ALTER COLUMN id SET DEFAULT nextval('public.session_sets_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: bot_user
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: workout_sessions id; Type: DEFAULT; Schema: public; Owner: bot_user
--

ALTER TABLE ONLY public.workout_sessions ALTER COLUMN id SET DEFAULT nextval('public.workout_sessions_id_seq'::regclass);


--
-- Name: workout_types id; Type: DEFAULT; Schema: public; Owner: bot_user
--

ALTER TABLE ONLY public.workout_types ALTER COLUMN id SET DEFAULT nextval('public.workout_types_id_seq'::regclass);


--
-- Name: exercises exercises_pkey; Type: CONSTRAINT; Schema: public; Owner: bot_user
--

ALTER TABLE ONLY public.exercises
    ADD CONSTRAINT exercises_pkey PRIMARY KEY (id);


--
-- Name: session_sets session_sets_pkey; Type: CONSTRAINT; Schema: public; Owner: bot_user
--

ALTER TABLE ONLY public.session_sets
    ADD CONSTRAINT session_sets_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: bot_user
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: workout_sessions workout_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: bot_user
--

ALTER TABLE ONLY public.workout_sessions
    ADD CONSTRAINT workout_sessions_pkey PRIMARY KEY (id);


--
-- Name: workout_types workout_types_pkey; Type: CONSTRAINT; Schema: public; Owner: bot_user
--

ALTER TABLE ONLY public.workout_types
    ADD CONSTRAINT workout_types_pkey PRIMARY KEY (id);


--
-- Name: ix_exercises_workout_type_id; Type: INDEX; Schema: public; Owner: bot_user
--

CREATE INDEX ix_exercises_workout_type_id ON public.exercises USING btree (workout_type_id);


--
-- Name: ix_session_sets_session_id; Type: INDEX; Schema: public; Owner: bot_user
--

CREATE INDEX ix_session_sets_session_id ON public.session_sets USING btree (session_id);


--
-- Name: ix_users_tg_id; Type: INDEX; Schema: public; Owner: bot_user
--

CREATE UNIQUE INDEX ix_users_tg_id ON public.users USING btree (tg_id);


--
-- Name: ix_workout_sessions_user_id; Type: INDEX; Schema: public; Owner: bot_user
--

CREATE INDEX ix_workout_sessions_user_id ON public.workout_sessions USING btree (user_id);


--
-- Name: ix_workout_types_user_id; Type: INDEX; Schema: public; Owner: bot_user
--

CREATE INDEX ix_workout_types_user_id ON public.workout_types USING btree (user_id);


--
-- Name: exercises exercises_workout_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bot_user
--

ALTER TABLE ONLY public.exercises
    ADD CONSTRAINT exercises_workout_type_id_fkey FOREIGN KEY (workout_type_id) REFERENCES public.workout_types(id) ON DELETE CASCADE;


--
-- Name: session_sets session_sets_exercise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bot_user
--

ALTER TABLE ONLY public.session_sets
    ADD CONSTRAINT session_sets_exercise_id_fkey FOREIGN KEY (exercise_id) REFERENCES public.exercises(id) ON DELETE RESTRICT;


--
-- Name: session_sets session_sets_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bot_user
--

ALTER TABLE ONLY public.session_sets
    ADD CONSTRAINT session_sets_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.workout_sessions(id) ON DELETE CASCADE;


--
-- Name: workout_sessions workout_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bot_user
--

ALTER TABLE ONLY public.workout_sessions
    ADD CONSTRAINT workout_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: workout_sessions workout_sessions_workout_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bot_user
--

ALTER TABLE ONLY public.workout_sessions
    ADD CONSTRAINT workout_sessions_workout_type_id_fkey FOREIGN KEY (workout_type_id) REFERENCES public.workout_types(id) ON DELETE RESTRICT;


--
-- Name: workout_types workout_types_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: bot_user
--

ALTER TABLE ONLY public.workout_types
    ADD CONSTRAINT workout_types_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict FpWc5M8dcXkpMPRUfslrUjwEQPuQipxV0xXKEKSDJBhH8ybS8xBFWaeOAc8YAGw

