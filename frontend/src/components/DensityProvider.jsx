import { createContext, useContext, useEffect, useState } from "react";

const DensityContext = createContext({
  density: "comfortable",
  setDensity: () => {},
});

const VALID = ["compact", "comfortable", "relaxed"];

export function DensityProvider({ children }) {
  const [density, setDensityState] = useState(() => {
    const stored = localStorage.getItem("fd-density");
    return VALID.includes(stored) ? stored : "comfortable";
  });

  useEffect(() => {
    localStorage.setItem("fd-density", density);
    document.documentElement.setAttribute("data-density", density);
  }, [density]);

  function setDensity(next) {
    if (VALID.includes(next)) setDensityState(next);
  }

  return (
    <DensityContext.Provider value={{ density, setDensity }}>
      {children}
    </DensityContext.Provider>
  );
}

export function useDensity() {
  return useContext(DensityContext);
}