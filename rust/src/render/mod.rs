//! Renderers for recovery intent and for the documents a tool prints.
//!
//! [`cli`] writes the line a shell user or an agent shelling out reads; [`prose`] writes the
//! sentence a caller that will never run a command reads. Both take the tool's name as an
//! argument, because neither the error nor the recovery knows it. [`view`] turns rows, records
//! and errors into the TOON blocks a tool prints on stdout, and truncates long text.

pub mod cli;
pub mod prose;
pub mod view;
